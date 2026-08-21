"""Pure-local contract for staged arm/gripper field acceptance.

This module validates policy and evidence records.  It never imports a vendor
runtime, opens a transport, creates a ROS graph, or executes an action.  An
``allowed`` result is only a machine-readable precondition result; it is not
hardware authorization and cannot replace physical isolation.
"""

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MATRIX_SCHEMA_ID = "limo.arm_gripper_field_acceptance_matrix"
MATRIX_SCHEMA_VERSION = 1
RECORD_SCHEMA_ID = "limo.arm_gripper_stage_entry_record"
RECORD_SCHEMA_VERSION = 1
AUTHORIZATION_SCOPE_SCHEMA_VERSION = 4

STAGE_IDS = (
    "A0", "A0-P", "A1", "A2", "A3", "A4", "A5-G", "A5-A")

BOUNDARY_PERMISSION_KEYS = (
    "field_activity_allowed",
    "ssh_allowed",
    "target_allowed",
    "device_access_allowed",
    "ros_graph_allowed",
    "vendor_runtime_allowed",
    "real_action_service_allowed",
    "hardware_connection_allowed",
    "motion_allowed",
)

ROOT_KEYS = (
    "schema_id",
    "schema_version",
    "matrix_revision",
    "current_task_boundary",
    "field_policy_release",
    "expected_release_bindings",
    "global_rules",
    "stages",
)

STAGE_KEYS = (
    "id",
    "kind",
    "operation",
    "current_disposition",
    "execution_permitted_in_current_task",
    "prerequisites",
    "authorization_scope",
    "one_time_authorization",
    "release_binding_kind",
    "requires_independent_stop",
    "requires_physical_isolation",
    "requires_persistent_latch",
    "motion_stage",
    "required_boundary_permissions",
    "required_evidence_keys",
    "failure_disposition",
)

RECORD_KEYS = (
    "schema_id",
    "schema_version",
    "record_id",
    "matrix_revision",
    "stage_id",
    "operation",
    "session_id",
    "operation_id",
    "completed_stage_evidence",
    "authorization",
    "release_binding",
    "selected_speed_grade",
    "transport_capabilities",
    "persistent_latch",
    "physical_isolation",
    "required_evidence",
)

AUTHORIZATION_KEYS = (
    "authorization_id",
    "external_authority",
    "authority_evidence_sha256",
    "scope",
    "session_id",
    "operation_id",
    "issued_at_utc",
    "not_before_utc",
    "expires_at_utc",
    "one_time",
    "max_uses",
    "scope_sha256",
    "credential_sha256",
    "clearance_id",
    "latch_snapshot_sha256",
    "command_id",
)

RELEASE_BINDING_KEYS = (
    "runtime_release_id",
    "release_manifest_sha256",
    "profile_id",
    "profile_manifest_sha256",
    "profile_runtime_release_id",
    "approved_speed_grades",
    "bounded_call_artifact_sha256",
    "stop_isolation_artifact_sha256",
    "hung_command_stop_report_sha256",
)

TRANSPORT_CAPABILITY_KEYS = (
    "bounded_calls_enforced",
    "native_deadline_enforced",
    "native_cancel_enforced",
    "python_timeout_thread_used",
    "independent_stop_channel",
    "independent_stop_lock_domain",
    "stop_not_queued_behind_commands",
    "hung_send_stop_completed_before_send_release",
    "persistent_physical_isolation_latch",
    "command_channel_id",
    "stop_channel_id",
    "command_lock_domain_id",
    "stop_lock_domain_id",
    "method_deadlines_s",
    "bounded_call_artifact_sha256",
    "stop_isolation_artifact_sha256",
    "hung_command_stop_report_sha256",
    "unresolved_stop_escalation",
)

METHOD_DEADLINE_KEYS = ("read_state", "command", "stop", "close")

PHYSICAL_ISOLATION_KEYS = (
    "verified",
    "zero_energy_verified",
    "physical_estop_verified",
    "evidence_sha256",
)

PERSISTENT_LATCH_KEYS = (
    "store_id",
    "status",
    "generation",
    "clearance_id",
    "latched_session_epoch",
    "clearing_session_epoch",
    "record_sha256",
    "snapshot_sha256",
    "session_binding_sha256",
    "runtime_release_id",
    "release_manifest_sha256",
    "profile_id",
    "profile_manifest_sha256",
    "external_clearance_validator_required",
    "protected_authority_evidence_sha256",
    "bounded_call_artifact_sha256",
    "stop_isolation_artifact_sha256",
    "hung_command_stop_report_sha256",
    "physical_isolation_evidence_sha256",
    "approval_artifact_sha256",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BOUNDARY_MODES = (
    "PERMANENT_LOCAL_ONLY",
    "ROS1_NOETIC_FAKE_ONLY",
    "FIELD_AUTHORIZED_POLICY",
)
MAX_NATIVE_DEADLINE_S = 60.0


PERMANENT_LOCAL_STAGE_STATES = {
    "A0": ("PASS_LOCAL", True),
    "A0-P": ("BLOCKED", True),
    "A1": ("BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER", False),
    "A2": ("BLOCKED", False),
    "A3": ("BLOCKED", False),
    "A4": ("BLOCKED", False),
    "A5-G": ("PROHIBITED", False),
    "A5-A": ("PROHIBITED", False),
}


ROS1_NOETIC_FAKE_ONLY_STAGE_STATES = {
    "A0": ("PASS_LOCAL", True),
    "A0-P": ("BLOCKED", True),
    "A1": ("ELIGIBLE", True),
    "A2": ("BLOCKED", False),
    "A3": ("BLOCKED", False),
    "A4": ("BLOCKED", False),
    "A5-G": ("PROHIBITED", False),
    "A5-A": ("PROHIBITED", False),
}


EXPECTED_STAGE_DEFINITIONS = {
    "A0": {
        "kind": "OFFLINE_SOURCE",
        "operation": "SOURCE_CONTRACT",
        "prerequisites": (),
        "authorization_scope": None,
        "one_time_authorization": False,
        "release_binding_kind": "NONE",
        "requires_independent_stop": False,
        "requires_physical_isolation": False,
        "requires_persistent_latch": False,
        "motion_stage": False,
        "required_boundary_permissions": (),
        "required_evidence_keys": (
            "local_test_report_sha256",
            "source_manifest_sha256",
        ),
        "failure_disposition": "BLOCKED",
    },
    "A0-P": {
        "kind": "OFFLINE_LATCH",
        "operation": "PROTECTED_LATCH",
        "prerequisites": (),
        "authorization_scope": None,
        "one_time_authorization": False,
        "release_binding_kind": "NONE",
        "requires_independent_stop": False,
        "requires_physical_isolation": False,
        "requires_persistent_latch": False,
        "motion_stage": False,
        "required_boundary_permissions": (),
        "required_evidence_keys": (
            "protected_storage_report_sha256",
            "power_loss_durability_report_sha256",
            "authenticity_authority_report_sha256",
        ),
        "failure_disposition": "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED",
    },
    "A1": {
        "kind": "OFFLINE_ROS1_NOETIC",
        "operation": "ROS1_NOETIC_DRY_RUN",
        "prerequisites": ("A0",),
        "authorization_scope": None,
        "one_time_authorization": False,
        "release_binding_kind": "NONE",
        "requires_independent_stop": False,
        "requires_physical_isolation": False,
        "requires_persistent_latch": False,
        "motion_stage": False,
        "required_boundary_permissions": ("ros_graph_allowed",),
        "required_evidence_keys": (
            "ros1_source_manifest_sha256",
            "ros1_catkin_build_log_sha256",
            "ros1_catkin_test_log_sha256",
            "ros1_callback_contract_log_sha256",
            "ros1_smoke_log_sha256",
            "ros1_ownership_audit_sha256",
            "ros1_cleanup_log_sha256",
        ),
        "failure_disposition": "BLOCKED",
    },
    "A2": {
        "kind": "FIELD_STATIC",
        "operation": "DEENERGIZED_STATIC_INSPECTION",
        "prerequisites": ("A0", "A0-P", "A1"),
        "authorization_scope": "A2_STATIC_ISOLATED_INSPECTION",
        "one_time_authorization": True,
        "release_binding_kind": "NONE",
        "requires_independent_stop": False,
        "requires_physical_isolation": True,
        "requires_persistent_latch": False,
        "motion_stage": False,
        "required_boundary_permissions": ("field_activity_allowed",),
        "required_evidence_keys": (
            "frozen_bom_sha256",
            "assembly_revision_sha256",
            "energy_isolation_diagram_sha256",
            "static_inspection_report_sha256",
        ),
        "failure_disposition": "BLOCKED",
    },
    "A3": {
        "kind": "FIELD_READ_ONLY",
        "operation": "ARM_PASSIVE_READ_ONLY",
        "prerequisites": ("A0", "A0-P", "A1", "A2"),
        "authorization_scope": "A3_ARM_READ_ONLY",
        "one_time_authorization": True,
        "release_binding_kind": "ARM",
        "requires_independent_stop": True,
        "requires_physical_isolation": True,
        "requires_persistent_latch": True,
        "motion_stage": False,
        "required_boundary_permissions": (
            "field_activity_allowed",
            "hardware_connection_allowed",
            "device_access_allowed",
        ),
        "required_evidence_keys": (
            "arm_identity_report_sha256",
            "transport_owner_report_sha256",
            "passive_read_proof_sha256",
            "limits_frames_tcp_report_sha256",
        ),
        "failure_disposition": "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED",
    },
    "A4": {
        "kind": "FIELD_READ_ONLY",
        "operation": "GRIPPER_PASSIVE_READ_ONLY",
        "prerequisites": ("A0", "A0-P", "A1", "A2", "A3"),
        "authorization_scope": "A4_GRIPPER_READ_ONLY",
        "one_time_authorization": True,
        "release_binding_kind": "GRIPPER",
        "requires_independent_stop": True,
        "requires_physical_isolation": True,
        "requires_persistent_latch": True,
        "motion_stage": False,
        "required_boundary_permissions": (
            "field_activity_allowed",
            "hardware_connection_allowed",
            "device_access_allowed",
        ),
        "required_evidence_keys": (
            "gripper_identity_report_sha256",
            "transport_owner_report_sha256",
            "passive_read_proof_sha256",
            "protocol_feedback_report_sha256",
        ),
        "failure_disposition": "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED",
    },
    "A5-G": {
        "kind": "FIELD_MOTION",
        "operation": "GRIPPER_FIRST_MOTION",
        "prerequisites": ("A0", "A0-P", "A1", "A2", "A3", "A4"),
        "authorization_scope": "A5_G_GRIPPER_FIRST_MOTION",
        "one_time_authorization": True,
        "release_binding_kind": "GRIPPER",
        "requires_independent_stop": True,
        "requires_physical_isolation": True,
        "requires_persistent_latch": True,
        "motion_stage": True,
        "required_boundary_permissions": (
            "field_activity_allowed",
            "hardware_connection_allowed",
            "device_access_allowed",
            "real_action_service_allowed",
            "motion_allowed",
        ),
        "required_evidence_keys": (
            "cleared_envelope_report_sha256",
            "first_motion_plan_sha256",
            "observer_log_sha256",
            "stop_response_plan_sha256",
        ),
        "failure_disposition": "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED",
    },
    "A5-A": {
        "kind": "FIELD_MOTION",
        "operation": "ARM_FIRST_MOTION",
        "prerequisites": ("A0", "A0-P", "A1", "A2", "A3", "A4"),
        "authorization_scope": "A5_A_ARM_FIRST_MOTION",
        "one_time_authorization": True,
        "release_binding_kind": "ARM",
        "requires_independent_stop": True,
        "requires_physical_isolation": True,
        "requires_persistent_latch": True,
        "motion_stage": True,
        "required_boundary_permissions": (
            "field_activity_allowed",
            "hardware_connection_allowed",
            "device_access_allowed",
            "real_action_service_allowed",
            "motion_allowed",
        ),
        "required_evidence_keys": (
            "cleared_envelope_report_sha256",
            "first_motion_plan_sha256",
            "observer_log_sha256",
            "stop_response_plan_sha256",
        ),
        "failure_disposition": "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED",
    },
}


@dataclass(frozen=True)
class AcceptanceIssue:
    code: str
    path: str
    message: str

    def as_dict(self):
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class MatrixValidationResult:
    errors: tuple

    @property
    def schema_valid(self):
        return not self.errors

    def as_dict(self):
        return {
            "schema_valid": self.schema_valid,
            "errors": [item.as_dict() for item in self.errors],
        }


@dataclass(frozen=True)
class StageEvaluationResult:
    allowed: bool
    errors: tuple
    blockers: tuple

    @property
    def field_entry_ready(self):
        return self.allowed

    def as_dict(self):
        return {
            "allowed": self.allowed,
            "field_entry_ready": self.field_entry_ready,
            "errors": [item.as_dict() for item in self.errors],
            "blockers": [item.as_dict() for item in self.blockers],
        }


class MatrixLoadError(ValueError):
    """Raised when strict JSON loading fails."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _clone_json_value(value, path="$"):
    """Clone only inert, exact JSON-domain values without invoking hooks."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise MatrixLoadError(
                "NONFINITE_JSON", "{} contains a non-finite number".format(
                    path))
        return value
    if type(value) is list:
        try:
            return [
                _clone_json_value(item, "{}[{}]".format(path, index))
                for index, item in enumerate(value)
            ]
        except RecursionError as error:
            raise MatrixLoadError(
                "JSON_TOO_DEEP", "JSON value is recursively nested") from error
    if type(value) is dict:
        result = {}
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise MatrixLoadError(
                        "NON_STRING_KEY",
                        "{} contains a non-string key".format(path),
                    )
                result[key] = _clone_json_value(
                    item, "{}.{}".format(path, key))
        except RecursionError as error:
            raise MatrixLoadError(
                "JSON_TOO_DEEP", "JSON value is recursively nested") from error
        return result
    raise MatrixLoadError(
        "NON_JSON_VALUE",
        "{} contains a non-JSON value".format(path),
    )


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MatrixLoadError(
                "DUPLICATE_KEY", "duplicate JSON key: {}".format(key))
        result[key] = value
    return result


def _reject_constant(value):
    raise MatrixLoadError(
        "NONFINITE_JSON", "non-finite JSON value: {}".format(value))


def loads_matrix(text):
    if type(text) is not str:
        raise MatrixLoadError("INVALID_INPUT", "JSON input must be a string")
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except MatrixLoadError:
        raise
    except (TypeError, ValueError) as error:
        raise MatrixLoadError("INVALID_JSON", str(error)) from error


def loads_record(text):
    """Strictly decode one stage-entry record."""
    return loads_matrix(text)


def load_matrix(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise MatrixLoadError("READ_FAILED", str(error)) from error
    return loads_matrix(text)


def load_record(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise MatrixLoadError("READ_FAILED", str(error)) from error
    return loads_record(text)


def _canonical_json_sha256(value):
    normalized = _clone_json_value(value)
    try:
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("value is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def canonical_matrix_payload_sha256(matrix):
    try:
        payload = _clone_json_value(matrix)
    except MatrixLoadError as error:
        raise ValueError(str(error)) from error
    if type(payload) is not dict:
        raise ValueError("matrix must be an exact object")
    release = payload.get("field_policy_release")
    if type(release) is not dict:
        raise ValueError("field_policy_release must be an exact object")
    release["matrix_payload_sha256"] = None
    return _canonical_json_sha256(payload)


def canonical_matrix_sha256(matrix):
    """Hash the exact frozen matrix, including its released payload hash."""
    try:
        return _canonical_json_sha256(matrix)
    except MatrixLoadError as error:
        raise ValueError(str(error)) from error


def _issue(items, code, path, message):
    items.append(AcceptanceIssue(code, path, message))


def _exact_keys(value, expected, path, errors):
    if type(value) is not dict:
        _issue(errors, "TYPE_MISMATCH", path, "must be an exact object")
        return False
    actual = set(value)
    required = set(expected)
    if actual != required:
        _issue(
            errors,
            "KEY_SET_MISMATCH",
            path,
            "expected keys {}; got {}".format(
                sorted(required), sorted(actual)),
        )
        return False
    return True


def _exact_string(value, path, errors, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        _issue(
            errors,
            "INVALID_STRING",
            path,
            "must be an exact non-empty trimmed string",
        )
        return None
    return value


def _exact_bool(value, path, errors):
    if type(value) is not bool:
        _issue(errors, "INVALID_BOOLEAN", path, "must be an exact boolean")
        return None
    return value


def _exact_int(value, path, errors, minimum=None, maximum=None):
    if type(value) is not int:
        _issue(errors, "INVALID_INTEGER", path, "must be an exact integer")
        return None
    if minimum is not None and value < minimum:
        _issue(
            errors, "INTEGER_OUT_OF_RANGE", path,
            "must be at least {}".format(minimum))
        return None
    if maximum is not None and value > maximum:
        _issue(
            errors, "INTEGER_OUT_OF_RANGE", path,
            "must not exceed {}".format(maximum))
        return None
    return value


def _utc_datetime(value, path, errors):
    parsed = _exact_string(value, path, errors)
    if parsed is None:
        return None
    if UTC_RE.fullmatch(parsed) is None:
        _issue(
            errors, "INVALID_UTC_TIMESTAMP", path,
            "must use exact YYYY-MM-DDTHH:MM:SSZ UTC format")
        return None
    try:
        return datetime.strptime(
            parsed, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        _issue(errors, "INVALID_UTC_TIMESTAMP", path, "is not a valid UTC time")
        return None


def _sha256(value, path, errors, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        _issue(
            errors,
            "INVALID_SHA256",
            path,
            "must be an exact lowercase SHA-256 digest",
        )
        return None
    return value


def _exact_string_list(value, path, errors):
    if type(value) is not list:
        _issue(errors, "TYPE_MISMATCH", path, "must be an exact array")
        return None
    resolved = []
    for index, item in enumerate(value):
        parsed = _exact_string(item, "{}[{}]".format(path, index), errors)
        if parsed is not None:
            resolved.append(parsed)
    if len(resolved) != len(set(resolved)):
        _issue(errors, "DUPLICATE_VALUE", path, "values must be unique")
    return tuple(resolved)


def _validate_release_binding(value, path, errors, binding_kind=None):
    if not _exact_keys(value, RELEASE_BINDING_KEYS, path, errors):
        return None
    runtime = _exact_string(
        value["runtime_release_id"], path + ".runtime_release_id", errors)
    release_sha = _sha256(
        value["release_manifest_sha256"],
        path + ".release_manifest_sha256",
        errors,
    )
    profile_id = _exact_string(
        value["profile_id"], path + ".profile_id", errors)
    profile_sha = _sha256(
        value["profile_manifest_sha256"],
        path + ".profile_manifest_sha256",
        errors,
    )
    profile_runtime = _exact_string(
        value["profile_runtime_release_id"],
        path + ".profile_runtime_release_id",
        errors,
    )
    bounded_call_sha = _sha256(
        value["bounded_call_artifact_sha256"],
        path + ".bounded_call_artifact_sha256",
        errors,
    )
    stop_isolation_sha = _sha256(
        value["stop_isolation_artifact_sha256"],
        path + ".stop_isolation_artifact_sha256",
        errors,
    )
    hung_stop_sha = _sha256(
        value["hung_command_stop_report_sha256"],
        path + ".hung_command_stop_report_sha256",
        errors,
    )
    grades = value["approved_speed_grades"]
    valid_grades = []
    if type(grades) is not list or not grades:
        _issue(
            errors,
            "INVALID_SPEED_GRADES",
            path + ".approved_speed_grades",
            "must be a non-empty exact array",
        )
    else:
        for index, grade in enumerate(grades):
            if type(grade) is not int or grade < 1 or grade > 100:
                _issue(
                    errors,
                    "INVALID_SPEED_GRADE",
                    "{}.approved_speed_grades[{}]".format(path, index),
                    "must be an exact integer in range 1..100",
                )
            else:
                valid_grades.append(grade)
        if valid_grades != sorted(set(valid_grades)):
            _issue(
                errors,
                "SPEED_GRADES_NOT_EXACT",
                path + ".approved_speed_grades",
                "must be unique and strictly increasing",
            )
    if runtime is not None and profile_runtime != runtime:
        _issue(
            errors,
            "PROFILE_RUNTIME_MISMATCH",
            path + ".profile_runtime_release_id",
            "must exactly match runtime_release_id",
        )
    bound_hashes = {
        "release_manifest_sha256": release_sha,
        "profile_manifest_sha256": profile_sha,
        "bounded_call_artifact_sha256": bounded_call_sha,
        "stop_isolation_artifact_sha256": stop_isolation_sha,
        "hung_command_stop_report_sha256": hung_stop_sha,
    }
    roles = tuple(bound_hashes)
    allowed_arm_reuse = frozenset((
        "bounded_call_artifact_sha256",
        "stop_isolation_artifact_sha256",
    ))
    for left_index, left_role in enumerate(roles):
        left_sha = bound_hashes[left_role]
        if left_sha is None:
            continue
        for right_role in roles[left_index + 1:]:
            if left_sha != bound_hashes[right_role]:
                continue
            role_pair = frozenset((left_role, right_role))
            if binding_kind == "ARM" and role_pair == allowed_arm_reuse:
                continue
            _issue(
                errors,
                "BINDING_HASH_REUSE",
                path,
                "artifact hashes may not be reused across evidence roles",
            )
    if errors:
        return None
    return {
        "runtime_release_id": runtime,
        "release_manifest_sha256": release_sha,
        "profile_id": profile_id,
        "profile_manifest_sha256": profile_sha,
        "profile_runtime_release_id": profile_runtime,
        "approved_speed_grades": tuple(valid_grades),
        "bounded_call_artifact_sha256": bounded_call_sha,
        "stop_isolation_artifact_sha256": stop_isolation_sha,
        "hung_command_stop_report_sha256": hung_stop_sha,
    }


def _validate_transport_capabilities(value, release_binding, path, errors):
    if not _exact_keys(value, TRANSPORT_CAPABILITY_KEYS, path, errors):
        return
    for key in (
            "bounded_calls_enforced",
            "native_deadline_enforced",
            "native_cancel_enforced",
            "independent_stop_channel",
            "independent_stop_lock_domain",
            "stop_not_queued_behind_commands",
            "hung_send_stop_completed_before_send_release",
            "persistent_physical_isolation_latch"):
        parsed = _exact_bool(value[key], path + "." + key, errors)
        if parsed is False:
            _issue(
                errors,
                "CAPABILITY_NOT_PROVEN",
                path + "." + key,
                "must be exact true",
            )
    timeout_thread = _exact_bool(
        value["python_timeout_thread_used"],
        path + ".python_timeout_thread_used", errors)
    if timeout_thread is True:
        _issue(
            errors,
            "PYTHON_TIMEOUT_THREAD_FORBIDDEN",
            path + ".python_timeout_thread_used",
            "a Python timeout thread is not native cancellation",
        )
    ids = {}
    for key in (
            "command_channel_id", "stop_channel_id",
            "command_lock_domain_id", "stop_lock_domain_id"):
        ids[key] = _exact_string(value[key], path + "." + key, errors)
    if (
            ids.get("command_channel_id") is not None
            and ids.get("command_channel_id")
            == ids.get("stop_channel_id")):
        _issue(
            errors,
            "STOP_CHANNEL_NOT_INDEPENDENT",
            path,
            "command and STOP channel IDs must be distinct",
        )
    if (
            ids.get("command_lock_domain_id") is not None
            and ids.get("command_lock_domain_id")
            == ids.get("stop_lock_domain_id")):
        _issue(
            errors,
            "STOP_LOCK_DOMAIN_NOT_INDEPENDENT",
            path,
            "command and STOP lock domains must be distinct",
        )
    deadlines = value["method_deadlines_s"]
    if _exact_keys(
            deadlines, METHOD_DEADLINE_KEYS,
            path + ".method_deadlines_s", errors):
        for key in METHOD_DEADLINE_KEYS:
            deadline = deadlines[key]
            if (
                    type(deadline) not in (int, float)
                    or not math.isfinite(deadline)
                    or deadline <= 0.0
                    or deadline > MAX_NATIVE_DEADLINE_S):
                _issue(
                    errors,
                    "INVALID_NATIVE_DEADLINE",
                    path + ".method_deadlines_s." + key,
                    "must be a finite native deadline in (0, 60] seconds",
                )
    bounded_call_sha = _sha256(
        value["bounded_call_artifact_sha256"],
        path + ".bounded_call_artifact_sha256",
        errors,
    )
    stop_isolation_sha = _sha256(
        value["stop_isolation_artifact_sha256"],
        path + ".stop_isolation_artifact_sha256",
        errors,
    )
    hung_stop_sha = _sha256(
        value["hung_command_stop_report_sha256"],
        path + ".hung_command_stop_report_sha256",
        errors,
    )
    if type(release_binding) is dict:
        expected_bounded_call_sha = release_binding.get(
            "bounded_call_artifact_sha256")
        if bounded_call_sha != expected_bounded_call_sha:
            _issue(
                errors,
                "TRANSPORT_BOUNDED_CALL_EVIDENCE_BINDING_MISMATCH",
                path + ".bounded_call_artifact_sha256",
                "transport must bind the approved bounded-call artifact",
            )
        expected_stop_isolation_sha = release_binding.get(
            "stop_isolation_artifact_sha256")
        if stop_isolation_sha != expected_stop_isolation_sha:
            _issue(
                errors,
                "TRANSPORT_STOP_ISOLATION_EVIDENCE_BINDING_MISMATCH",
                path + ".stop_isolation_artifact_sha256",
                "transport must bind the approved STOP-isolation artifact",
            )
        expected_hung_stop_sha = release_binding.get(
            "hung_command_stop_report_sha256")
        if hung_stop_sha != expected_hung_stop_sha:
            _issue(
                errors,
                "TRANSPORT_HUNG_STOP_EVIDENCE_BINDING_MISMATCH",
                path + ".hung_command_stop_report_sha256",
                "transport must bind the approved hung-command STOP report",
            )
    if (
            value["unresolved_stop_escalation"]
            != "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED"):
        _issue(
            errors,
            "INVALID_STOP_ESCALATION",
            path + ".unresolved_stop_escalation",
            "must require persistent physical isolation",
        )


def _validate_persistent_latch(
        value, release_binding, transport_capabilities, authorization,
        physical_isolation, path, errors):
    if not _exact_keys(value, PERSISTENT_LATCH_KEYS, path, errors):
        return
    _exact_string(value["store_id"], path + ".store_id", errors)
    if value["status"] != "CLEAR":
        _issue(
            errors, "PERSISTENT_LATCH_NOT_CLEAR", path + ".status",
            "stage entry requires an externally verified CLEAR snapshot")
    _exact_int(value["generation"], path + ".generation", errors, minimum=3)
    clearance_id = _exact_string(
        value["clearance_id"], path + ".clearance_id", errors)
    latched_epoch = _exact_int(
        value["latched_session_epoch"],
        path + ".latched_session_epoch", errors, minimum=1)
    clearing_epoch = _exact_int(
        value["clearing_session_epoch"],
        path + ".clearing_session_epoch", errors, minimum=2)
    if (
            latched_epoch is not None
            and clearing_epoch is not None
            and clearing_epoch <= latched_epoch):
        _issue(
            errors,
            "LATCH_SESSION_EPOCH_NOT_MONOTONIC",
            path + ".clearing_session_epoch",
            "CLEAR requires a strictly newer external session epoch",
        )
    for key in (
            "record_sha256", "snapshot_sha256", "session_binding_sha256",
            "release_manifest_sha256", "profile_manifest_sha256",
            "protected_authority_evidence_sha256",
            "bounded_call_artifact_sha256",
            "stop_isolation_artifact_sha256",
            "hung_command_stop_report_sha256",
            "physical_isolation_evidence_sha256",
            "approval_artifact_sha256"):
        _sha256(value[key], path + "." + key, errors)
    for key in ("runtime_release_id", "profile_id"):
        _exact_string(value[key], path + "." + key, errors)
    required = _exact_bool(
        value["external_clearance_validator_required"],
        path + ".external_clearance_validator_required", errors)
    if required is not True:
        _issue(
            errors, "EXTERNAL_CLEARANCE_VALIDATOR_REQUIRED",
            path + ".external_clearance_validator_required",
            "must be exact true")
    expected = {
        "runtime_release_id": release_binding.get("runtime_release_id"),
        "release_manifest_sha256": release_binding.get(
            "release_manifest_sha256"),
        "profile_id": release_binding.get("profile_id"),
        "profile_manifest_sha256": release_binding.get(
            "profile_manifest_sha256"),
    }
    for key, expected_value in expected.items():
        if value[key] != expected_value or type(value[key]) is not type(
                expected_value):
            _issue(
                errors, "LATCH_RELEASE_BINDING_MISMATCH",
                path + "." + key,
                "persistent latch must bind the exact release/profile")
    evidence_codes = {
        "bounded_call_artifact_sha256": (
            "LATCH_BOUNDED_CALL_EVIDENCE_BINDING_MISMATCH"),
        "stop_isolation_artifact_sha256": (
            "LATCH_STOP_ISOLATION_EVIDENCE_BINDING_MISMATCH"),
        "hung_command_stop_report_sha256": (
            "LATCH_HUNG_STOP_EVIDENCE_BINDING_MISMATCH"),
    }
    for key, code in evidence_codes.items():
        latch_sha = value[key]
        release_sha = release_binding.get(key)
        transport_sha = (
            transport_capabilities.get(key)
            if type(transport_capabilities) is dict else None)
        if (
                latch_sha != release_sha
                or type(latch_sha) is not type(release_sha)
                or latch_sha != transport_sha
                or type(latch_sha) is not type(transport_sha)):
            _issue(
                errors,
                code,
                path + "." + key,
                "latch must bind the exact release and transport evidence",
            )
    authorization_clearance = authorization.get("clearance_id")
    if (
            clearance_id is not None
            and (
                type(authorization_clearance) is not str
                or clearance_id != authorization_clearance)):
        _issue(
            errors, "LATCH_CLEARANCE_MISMATCH", path + ".clearance_id",
            "latch CLEAR must bind the exact authorization clearance_id")
    if value["snapshot_sha256"] != authorization.get(
            "latch_snapshot_sha256"):
        _issue(
            errors, "LATCH_SNAPSHOT_MISMATCH", path + ".snapshot_sha256",
            "authorization and latch must bind the same snapshot")
    physical_evidence = (
        physical_isolation.get("evidence_sha256")
        if type(physical_isolation) is dict else None)
    if value["physical_isolation_evidence_sha256"] != physical_evidence:
        _issue(
            errors,
            "LATCH_PHYSICAL_ISOLATION_MISMATCH",
            path + ".physical_isolation_evidence_sha256",
            "latch CLEAR must bind the exact physical-isolation artifact",
        )
    if value["approval_artifact_sha256"] != authorization.get(
            "authority_evidence_sha256"):
        _issue(
            errors,
            "LATCH_APPROVAL_ARTIFACT_MISMATCH",
            path + ".approval_artifact_sha256",
            "latch CLEAR must bind the exact external approval artifact",
        )


def _validate_physical_isolation(value, path, errors):
    if not _exact_keys(value, PHYSICAL_ISOLATION_KEYS, path, errors):
        return
    for key in ("verified", "zero_energy_verified", "physical_estop_verified"):
        parsed = _exact_bool(value[key], path + "." + key, errors)
        if parsed is False:
            _issue(
                errors,
                "PHYSICAL_ISOLATION_NOT_PROVEN",
                path + "." + key,
                "must be exact true",
            )
    _sha256(value["evidence_sha256"], path + ".evidence_sha256", errors)


def _validate_authorization(
        value, stage, session_id, operation_id, path, errors):
    if not _exact_keys(value, AUTHORIZATION_KEYS, path, errors):
        return
    for key in (
            "authorization_id", "scope", "session_id", "operation_id"):
        _exact_string(value[key], path + "." + key, errors)
    external = _exact_bool(
        value["external_authority"], path + ".external_authority", errors)
    if external is not True:
        _issue(
            errors, "EXTERNAL_AUTHORITY_REQUIRED",
            path + ".external_authority", "must be exact true")
    _sha256(
        value["authority_evidence_sha256"],
        path + ".authority_evidence_sha256", errors)
    issued = _utc_datetime(
        value["issued_at_utc"], path + ".issued_at_utc", errors)
    not_before = _utc_datetime(
        value["not_before_utc"], path + ".not_before_utc", errors)
    expires = _utc_datetime(
        value["expires_at_utc"], path + ".expires_at_utc", errors)
    if issued is not None and not_before is not None and issued > not_before:
        _issue(
            errors, "AUTHORIZATION_TIME_ORDER_INVALID",
            path + ".not_before_utc",
            "not-before time cannot precede issue time")
    if (
            not_before is not None and expires is not None
            and not_before >= expires):
        _issue(
            errors, "AUTHORIZATION_TIME_ORDER_INVALID",
            path + ".expires_at_utc",
            "expiry must be later than not-before time")
    _sha256(value["scope_sha256"], path + ".scope_sha256", errors)
    _sha256(value["credential_sha256"], path + ".credential_sha256", errors)
    if value["scope"] != stage["authorization_scope"]:
        _issue(
            errors,
            "AUTHORIZATION_SCOPE_MISMATCH",
            path + ".scope",
            "authorization is not valid for this exact stage",
        )
    if value["session_id"] != session_id:
        _issue(
            errors,
            "AUTHORIZATION_SESSION_MISMATCH",
            path + ".session_id",
            "authorization must bind the exact session",
        )
    if value["operation_id"] != operation_id:
        _issue(
            errors,
            "AUTHORIZATION_OPERATION_MISMATCH",
            path + ".operation_id",
            "authorization must bind the exact one-time operation",
        )
    if type(value["one_time"]) is not bool or value["one_time"] is not True:
        _issue(
            errors,
            "AUTHORIZATION_NOT_ONE_TIME",
            path + ".one_time",
            "must be exact true",
        )
    max_uses = _exact_int(
        value["max_uses"], path + ".max_uses", errors,
        minimum=1, maximum=1)
    if max_uses != 1:
        _issue(
            errors, "AUTHORIZATION_NOT_ONE_TIME", path + ".max_uses",
            "must be exact integer 1")
    if stage["requires_persistent_latch"]:
        _exact_string(value["clearance_id"], path + ".clearance_id", errors)
        _sha256(
            value["latch_snapshot_sha256"],
            path + ".latch_snapshot_sha256",
            errors,
        )
    else:
        for key in ("clearance_id", "latch_snapshot_sha256"):
            if value[key] is not None:
                _issue(
                    errors,
                    "UNEXPECTED_LATCH_CREDENTIAL",
                    path + "." + key,
                    "must be null when this stage has no persistent latch",
                )
    if stage["motion_stage"]:
        _exact_string(value["command_id"], path + ".command_id", errors)
    elif value["command_id"] is not None:
        _issue(
            errors,
            "UNEXPECTED_MOTION_CREDENTIAL",
            path + ".command_id",
            "must be null for a non-motion stage",
        )


def canonical_authorization_scope_sha256(matrix, record):
    """Bind one authorization to the complete inert stage-entry scope.

    Authorization, transport, latch and physical-isolation records are
    included as complete canonical JSON objects.  ``scope_sha256`` itself is
    normalized to null to avoid self-reference.  Selecting only headline
    evidence hashes is unsafe because a credential could otherwise survive a
    change to a native deadline, channel/lock identity, clearance, latch
    generation or another safety field.
    """
    try:
        matrix_value = _clone_json_value(matrix, "$matrix")
        record_value = _clone_json_value(record, "$record")
    except MatrixLoadError as error:
        raise ValueError(str(error)) from error
    if type(record_value) is not dict:
        raise ValueError("record must be an exact object")
    authorization = record_value.get("authorization")
    if type(authorization) is not dict:
        raise ValueError("record authorization must be an exact object")
    authorization_scope = dict(authorization)
    authorization_scope["scope_sha256"] = None
    capabilities = record_value.get("transport_capabilities")
    latch = record_value.get("persistent_latch")
    isolation = record_value.get("physical_isolation")
    payload = {
        "schema_id": "limo.arm_gripper_authorization_scope",
        "schema_version": AUTHORIZATION_SCOPE_SCHEMA_VERSION,
        "policy_sha256": canonical_matrix_sha256(matrix_value),
        "record_id": record_value.get("record_id"),
        "matrix_revision": record_value.get("matrix_revision"),
        "stage_id": record_value.get("stage_id"),
        "operation": record_value.get("operation"),
        "session_id": record_value.get("session_id"),
        "operation_id": record_value.get("operation_id"),
        "authorization": authorization_scope,
        "completed_stage_evidence": record_value.get(
            "completed_stage_evidence"),
        "release_binding": record_value.get("release_binding"),
        "selected_speed_grade": record_value.get("selected_speed_grade"),
        "transport_capabilities": capabilities,
        "persistent_latch": latch,
        "physical_isolation": isolation,
        "required_evidence": record_value.get("required_evidence"),
    }
    return _canonical_json_sha256(payload)


def validate_matrix_definition(matrix):
    errors = []
    try:
        matrix = _clone_json_value(matrix)
    except MatrixLoadError as error:
        _issue(errors, error.code, "$", str(error))
        return MatrixValidationResult(tuple(errors))
    if not _exact_keys(matrix, ROOT_KEYS, "$", errors):
        return MatrixValidationResult(tuple(errors))
    if matrix["schema_id"] != MATRIX_SCHEMA_ID:
        _issue(errors, "SCHEMA_ID_MISMATCH", "$.schema_id", "unexpected schema")
    if type(matrix["schema_version"]) is not int or matrix["schema_version"] != 1:
        _issue(
            errors, "SCHEMA_VERSION_MISMATCH", "$.schema_version",
            "schema version must be exact integer 1")
    _exact_string(matrix["matrix_revision"], "$.matrix_revision", errors)

    boundary = matrix["current_task_boundary"]
    boundary_keys = ("mode",) + BOUNDARY_PERMISSION_KEYS
    if _exact_keys(boundary, boundary_keys, "$.current_task_boundary", errors):
        mode = boundary["mode"]
        if mode not in BOUNDARY_MODES:
            _issue(
                errors, "INVALID_BOUNDARY_MODE",
                "$.current_task_boundary.mode", "unknown boundary mode")
        for key in BOUNDARY_PERMISSION_KEYS:
            _exact_bool(
                boundary[key], "$.current_task_boundary." + key, errors)
        if mode == "PERMANENT_LOCAL_ONLY":
            for key in BOUNDARY_PERMISSION_KEYS:
                if boundary[key] is not False:
                    _issue(
                        errors,
                        "LOCAL_ONLY_PERMISSION_ENABLED",
                        "$.current_task_boundary." + key,
                        "all permissions must be exact false",
                    )
        elif mode == "ROS1_NOETIC_FAKE_ONLY":
            for key in BOUNDARY_PERMISSION_KEYS:
                expected_value = key == "ros_graph_allowed"
                if boundary[key] is not expected_value:
                    _issue(
                        errors,
                        "ROS1_FAKE_ONLY_PERMISSION_MISMATCH",
                        "$.current_task_boundary." + key,
                        "only ros_graph_allowed may be exact true",
                    )

    release = matrix["field_policy_release"]
    release_keys = (
        "release_id", "matrix_payload_sha256",
        "authority_evidence_sha256", "external_authority", "reviewed")
    if _exact_keys(release, release_keys, "$.field_policy_release", errors):
        mode = boundary.get("mode") if type(boundary) is dict else None
        if mode in ("PERMANENT_LOCAL_ONLY", "ROS1_NOETIC_FAKE_ONLY"):
            for key in (
                    "release_id", "matrix_payload_sha256",
                    "authority_evidence_sha256"):
                if release[key] is not None:
                    _issue(
                        errors,
                        "NON_FIELD_RELEASE_PRESENT",
                        "$.field_policy_release." + key,
                        "must be null outside field-authorized mode",
                    )
            if release["reviewed"] is not False:
                _issue(
                    errors,
                    "NON_FIELD_RELEASE_REVIEWED",
                    "$.field_policy_release.reviewed",
                    "must be exact false outside field-authorized mode",
                )
            if release["external_authority"] is not False:
                _issue(
                    errors,
                    "NON_FIELD_EXTERNAL_AUTHORITY_PRESENT",
                    "$.field_policy_release.external_authority",
                    "must be exact false outside field-authorized mode",
                )
        else:
            _exact_string(
                release["release_id"], "$.field_policy_release.release_id",
                errors)
            payload_sha = _sha256(
                release["matrix_payload_sha256"],
                "$.field_policy_release.matrix_payload_sha256", errors)
            _sha256(
                release["authority_evidence_sha256"],
                "$.field_policy_release.authority_evidence_sha256", errors)
            if _exact_bool(
                    release["external_authority"],
                    "$.field_policy_release.external_authority",
                    errors) is not True:
                _issue(
                    errors, "FIELD_POLICY_EXTERNAL_AUTHORITY_REQUIRED",
                    "$.field_policy_release.external_authority",
                    "must be exact true")
            if _exact_bool(
                    release["reviewed"],
                    "$.field_policy_release.reviewed", errors) is not True:
                _issue(
                    errors, "FIELD_POLICY_NOT_REVIEWED",
                    "$.field_policy_release.reviewed", "must be exact true")
            if payload_sha is not None:
                try:
                    actual_sha = canonical_matrix_payload_sha256(matrix)
                except ValueError as error:
                    _issue(
                        errors, "CANONICALIZATION_FAILED", "$", str(error))
                else:
                    if actual_sha != payload_sha:
                        _issue(
                            errors,
                            "MATRIX_PAYLOAD_HASH_MISMATCH",
                            "$.field_policy_release.matrix_payload_sha256",
                            "does not bind the exact matrix payload",
                        )

    bindings = matrix["expected_release_bindings"]
    if _exact_keys(
            bindings, ("ARM", "GRIPPER"),
            "$.expected_release_bindings", errors):
        for kind in ("ARM", "GRIPPER"):
            value = bindings[kind]
            mode = boundary.get("mode") if type(boundary) is dict else None
            if mode != "FIELD_AUTHORIZED_POLICY" and value is not None:
                _issue(
                    errors,
                    "NON_FIELD_RELEASE_BINDING_PRESENT",
                    "$.expected_release_bindings." + kind,
                    "real release bindings must be null outside field mode",
                )
            if value is not None:
                local_errors = []
                _validate_release_binding(
                    value,
                    "$.expected_release_bindings." + kind,
                    local_errors,
                    binding_kind=kind,
                )
                errors.extend(local_errors)

    rules = matrix["global_rules"]
    rule_keys = (
        "software_stop_is_safety_rated",
        "self_declared_authorization_is_valid",
        "blank_tbd_or_estimated_evidence_can_pass",
        "later_stage_can_bypass_failed_prerequisite",
        "arm_and_gripper_motion_authorizations_are_interchangeable",
        "offline_engineering_can_continue_while_field_blocked",
        "stage_order",
    )
    if _exact_keys(rules, rule_keys, "$.global_rules", errors):
        for key in rule_keys[:-1]:
            _exact_bool(rules[key], "$.global_rules." + key, errors)
        for key in rule_keys[:5]:
            if rules[key] is not False:
                _issue(
                    errors, "UNSAFE_GLOBAL_RULE", "$.global_rules." + key,
                    "must be exact false")
        if rules["offline_engineering_can_continue_while_field_blocked"] is not True:
            _issue(
                errors, "OFFLINE_PROGRESS_RULE_MISSING",
                "$.global_rules.offline_engineering_can_continue_while_field_blocked",
                "must be exact true")
        order = _exact_string_list(
            rules["stage_order"], "$.global_rules.stage_order", errors)
        if order is not None and order != STAGE_IDS:
            _issue(
                errors, "STAGE_ORDER_MISMATCH", "$.global_rules.stage_order",
                "must exactly match the staged contract")

    stages = matrix["stages"]
    if type(stages) is not list:
        _issue(errors, "TYPE_MISMATCH", "$.stages", "must be an exact array")
        return MatrixValidationResult(tuple(errors))
    ids = []
    for index, stage in enumerate(stages):
        path = "$.stages[{}]".format(index)
        if not _exact_keys(stage, STAGE_KEYS, path, errors):
            continue
        stage_id = _exact_string(stage["id"], path + ".id", errors)
        ids.append(stage_id)
        expected = EXPECTED_STAGE_DEFINITIONS.get(stage_id)
        if expected is None:
            _issue(errors, "UNKNOWN_STAGE", path + ".id", "stage is not allowed")
            continue
        for key in (
                "kind", "operation", "authorization_scope",
                "release_binding_kind", "failure_disposition"):
            if stage[key] != expected[key]:
                _issue(
                    errors, "STAGE_DEFINITION_MISMATCH", path + "." + key,
                    "does not match the frozen stage definition")
        for key in (
                "one_time_authorization", "requires_independent_stop",
                "requires_physical_isolation", "requires_persistent_latch",
                "motion_stage"):
            _exact_bool(stage[key], path + "." + key, errors)
            if stage[key] is not expected[key]:
                _issue(
                    errors, "STAGE_DEFINITION_MISMATCH", path + "." + key,
                    "does not match the frozen stage definition")
        for key in (
                "prerequisites", "required_boundary_permissions",
                "required_evidence_keys"):
            parsed = _exact_string_list(
                stage[key], path + "." + key, errors)
            if parsed is not None and parsed != expected[key]:
                _issue(
                    errors, "STAGE_DEFINITION_MISMATCH", path + "." + key,
                    "does not match the frozen stage definition")
        disposition = stage["current_disposition"]
        if disposition not in (
                "PASS_LOCAL", "BLOCKED", "FAIL_BEFORE_BUILD",
                "BLOCKED_NO_ROS1_ARM_GRIPPER_ADAPTER",
                "PROHIBITED", "ELIGIBLE"):
            _issue(
                errors, "INVALID_DISPOSITION",
                path + ".current_disposition", "unknown disposition")
        permitted = _exact_bool(
            stage["execution_permitted_in_current_task"],
            path + ".execution_permitted_in_current_task", errors)
        mode = boundary.get("mode") if type(boundary) is dict else None
        if mode == "PERMANENT_LOCAL_ONLY":
            local_expected = PERMANENT_LOCAL_STAGE_STATES[stage_id]
            if (disposition, permitted) != local_expected:
                _issue(
                    errors,
                    "LOCAL_ONLY_STAGE_STATE_MISMATCH",
                    path,
                    "stage state does not match the permanent boundary",
                )
        elif mode == "ROS1_NOETIC_FAKE_ONLY":
            noetic_expected = ROS1_NOETIC_FAKE_ONLY_STAGE_STATES[stage_id]
            if (disposition, permitted) != noetic_expected:
                _issue(
                    errors,
                    "ROS1_FAKE_ONLY_STAGE_STATE_MISMATCH",
                    path,
                    "stage state does not match the ROS1 fake-only boundary",
                )
        elif mode == "FIELD_AUTHORIZED_POLICY":
            if expected["kind"].startswith("FIELD_"):
                allowed_states = {
                    ("BLOCKED", False),
                    ("ELIGIBLE", True),
                    ("PROHIBITED", False),
                }
                if (disposition, permitted) not in allowed_states:
                    _issue(
                        errors,
                        "FIELD_STAGE_STATE_INVALID",
                        path,
                        "field stages may be BLOCKED, ELIGIBLE or PROHIBITED; "
                        "PASS_LOCAL is forbidden",
                    )
            else:
                allowed_states = {
                    ("BLOCKED", False),
                    ("PASS_LOCAL", False),
                }
                if (disposition, permitted) not in allowed_states:
                    _issue(
                        errors,
                        "FIELD_POLICY_OFFLINE_STAGE_STATE_INVALID",
                        path,
                        "offline stages cannot execute in field mode and must "
                        "be either BLOCKED or previously PASS_LOCAL",
                    )
    if tuple(ids) != STAGE_IDS:
        _issue(
            errors, "STAGE_SET_MISMATCH", "$.stages",
            "stages must appear exactly once in frozen order")
    if len(ids) != len(set(ids)):
        _issue(errors, "DUPLICATE_STAGE", "$.stages", "stage IDs must be unique")

    mode = boundary.get("mode") if type(boundary) is dict else None
    if (
            mode == "FIELD_AUTHORIZED_POLICY"
            and tuple(ids) == STAGE_IDS
            and not errors):
        stages_by_id = {stage["id"]: stage for stage in stages}
        for stage in stages:
            stage_expected = EXPECTED_STAGE_DEFINITIONS[stage["id"]]
            if (
                    stage_expected["kind"].startswith("FIELD_")
                    and stage["current_disposition"] == "ELIGIBLE"):
                for prerequisite_id in stage["prerequisites"]:
                    prerequisite = stages_by_id[prerequisite_id]
                    prerequisite_expected = EXPECTED_STAGE_DEFINITIONS[
                        prerequisite_id]
                    if (
                            not prerequisite_expected["kind"].startswith(
                                "FIELD_")
                            and prerequisite["current_disposition"]
                            != "PASS_LOCAL"):
                        _issue(
                            errors,
                            "FIELD_OFFLINE_PREREQUISITE_NOT_COMPLETE",
                            "$.stages.{}".format(stage["id"]),
                            "eligible field stage requires offline prerequisite "
                            "{} to be PASS_LOCAL".format(prerequisite_id),
                        )

    return MatrixValidationResult(tuple(errors))


def _validate_record_structure(record, matrix, stage):
    errors = []
    if not _exact_keys(record, RECORD_KEYS, "$record", errors):
        return errors
    if record["schema_id"] != RECORD_SCHEMA_ID:
        _issue(
            errors, "RECORD_SCHEMA_ID_MISMATCH", "$record.schema_id",
            "unexpected record schema")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        _issue(
            errors, "RECORD_SCHEMA_VERSION_MISMATCH",
            "$record.schema_version", "must be exact integer 1")
    _exact_string(record["record_id"], "$record.record_id", errors)
    _exact_string(record["session_id"], "$record.session_id", errors)
    _exact_string(record["operation_id"], "$record.operation_id", errors)
    if record["matrix_revision"] != matrix["matrix_revision"]:
        _issue(
            errors, "MATRIX_REVISION_MISMATCH", "$record.matrix_revision",
            "record does not bind the exact matrix revision")
    if record["stage_id"] != stage["id"]:
        _issue(
            errors, "STAGE_ID_MISMATCH", "$record.stage_id",
            "record does not bind the requested stage")
    if record["operation"] != stage["operation"]:
        _issue(
            errors, "OPERATION_MISMATCH", "$record.operation",
            "record does not bind the exact stage operation")

    completed = record["completed_stage_evidence"]
    prerequisites = tuple(stage["prerequisites"])
    if type(completed) is not dict:
        _issue(
            errors, "TYPE_MISMATCH", "$record.completed_stage_evidence",
            "must be an exact object")
    elif set(completed) != set(prerequisites):
        _issue(
            errors, "PREREQUISITE_EVIDENCE_MISMATCH",
            "$record.completed_stage_evidence",
            "must contain exactly the prerequisite stages")
    else:
        for stage_id, digest in completed.items():
            _sha256(
                digest,
                "$record.completed_stage_evidence." + stage_id,
                errors,
            )

    evidence = record["required_evidence"]
    required_keys = tuple(stage["required_evidence_keys"])
    if type(evidence) is not dict:
        _issue(
            errors, "TYPE_MISMATCH", "$record.required_evidence",
            "must be an exact object")
    elif set(evidence) != set(required_keys):
        _issue(
            errors, "REQUIRED_EVIDENCE_MISMATCH",
            "$record.required_evidence",
            "blank, TBD, estimated, missing or extra evidence cannot pass")
    else:
        for key, digest in evidence.items():
            _sha256(digest, "$record.required_evidence." + key, errors)

    authorization = record["authorization"]
    if stage["one_time_authorization"]:
        if type(authorization) is not dict:
            _issue(
                errors, "AUTHORIZATION_REQUIRED", "$record.authorization",
                "a stage-specific one-time authorization is required")
        else:
            _validate_authorization(
                authorization, stage, record["session_id"],
                record["operation_id"],
                "$record.authorization", errors)
    elif authorization is not None:
        _issue(
            errors, "UNEXPECTED_AUTHORIZATION", "$record.authorization",
            "offline stages must not carry a field authorization")

    binding_kind = stage["release_binding_kind"]
    binding = record["release_binding"]
    selected_speed_grade = record["selected_speed_grade"]
    if binding_kind == "NONE":
        if binding is not None:
            _issue(
                errors, "UNEXPECTED_RELEASE_BINDING",
                "$record.release_binding", "must be null for this stage")
        if selected_speed_grade is not None:
            _issue(
                errors, "UNEXPECTED_SPEED_GRADE",
                "$record.selected_speed_grade",
                "must be null when there is no release binding")
    elif type(binding) is not dict:
        _issue(
            errors, "RELEASE_BINDING_REQUIRED", "$record.release_binding",
            "exact runtime/profile binding is required")
    else:
        local_errors = []
        _validate_release_binding(
            binding, "$record.release_binding", local_errors,
            binding_kind=binding_kind)
        errors.extend(local_errors)
        expected = matrix["expected_release_bindings"][binding_kind]
        if expected is None or binding != expected:
            _issue(
                errors, "RELEASE_BINDING_MISMATCH",
                "$record.release_binding",
                "does not match the approved exact binding")
        if stage["motion_stage"]:
            grade = _exact_int(
                selected_speed_grade, "$record.selected_speed_grade", errors,
                minimum=1, maximum=100)
            if (
                    grade is not None
                    and grade not in binding.get("approved_speed_grades", [])):
                _issue(
                    errors, "SPEED_GRADE_NOT_APPROVED",
                    "$record.selected_speed_grade",
                    "must be a member of the exact approved speed grades")
        elif selected_speed_grade is not None:
            _issue(
                errors, "UNEXPECTED_SPEED_GRADE",
                "$record.selected_speed_grade",
                "read-only stages must not select a motion speed grade")

    capabilities = record["transport_capabilities"]
    if stage["requires_independent_stop"]:
        if type(capabilities) is not dict:
            _issue(
                errors, "TRANSPORT_CAPABILITIES_REQUIRED",
                "$record.transport_capabilities",
                "native deadlines/cancel and independent STOP are required")
        else:
            _validate_transport_capabilities(
                capabilities, binding,
                "$record.transport_capabilities", errors)
    elif capabilities is not None:
        _issue(
            errors, "UNEXPECTED_TRANSPORT_CAPABILITIES",
            "$record.transport_capabilities", "must be null for this stage")

    isolation = record["physical_isolation"]
    latch = record["persistent_latch"]
    if stage["requires_persistent_latch"]:
        if type(latch) is not dict:
            _issue(
                errors, "PERSISTENT_LATCH_REQUIRED",
                "$record.persistent_latch",
                "an exact release-bound CLEAR latch snapshot is required")
        elif type(binding) is dict and type(authorization) is dict:
            _validate_persistent_latch(
                latch, binding, capabilities, authorization, isolation,
                "$record.persistent_latch", errors)
    elif latch is not None:
        _issue(
            errors, "UNEXPECTED_PERSISTENT_LATCH",
            "$record.persistent_latch", "must be null for this stage")

    if stage["requires_physical_isolation"]:
        if type(isolation) is not dict:
            _issue(
                errors, "PHYSICAL_ISOLATION_REQUIRED",
                "$record.physical_isolation",
                "physical isolation evidence is required")
        else:
            _validate_physical_isolation(
                isolation, "$record.physical_isolation", errors)
    elif isolation is not None:
        _issue(
            errors, "UNEXPECTED_PHYSICAL_ISOLATION",
            "$record.physical_isolation", "must be null for this stage")
    if type(authorization) is dict:
        try:
            expected_scope_sha = canonical_authorization_scope_sha256(
                matrix, record)
        except ValueError as error:
            _issue(
                errors, "AUTHORIZATION_SCOPE_CANONICALIZATION_FAILED",
                "$record.authorization.scope_sha256", str(error))
        else:
            if authorization.get("scope_sha256") != expected_scope_sha:
                _issue(
                    errors, "AUTHORIZATION_SCOPE_HASH_MISMATCH",
                    "$record.authorization.scope_sha256",
                    "does not bind the exact policy/stage/session/operation/"
                    "authorization/release/transport/latch/isolation scope")
    return errors


def _call_validator(validator, args, code, path, message, blockers):
    if not callable(validator):
        _issue(blockers, code, path, message)
        return False
    try:
        safe_args = tuple(
            _clone_json_value(value, "$callback_arg[{}]".format(index))
            for index, value in enumerate(args))
        result = validator(*safe_args)
    except Exception as error:
        _issue(
            blockers, code, path,
            "{}: {}".format(message, type(error).__name__))
        return False
    if result is not True:
        _issue(blockers, code, path, message + "; exact true required")
        return False
    return True


def evaluate_stage_entry(
        matrix,
        record,
        *,
        trusted_boundary_mode=None,
        trusted_policy_digest=None,
        trusted_now_utc=None,
        policy_authority_validator=None,
        stage_evidence_validator=None,
        authorization_authority_validator=None,
        release_binding_validator=None,
        transport_capability_validator=None,
        persistent_latch_validator=None,
        physical_isolation_validator=None,
        evidence_validator=None,
        authorization_consumer=None):
    """Evaluate a stage-entry record without importing or touching hardware.

    ``trusted_boundary_mode`` and ``trusted_policy_digest`` are caller-owned
    authority inputs.  A matrix cannot authorize itself by changing its own
    boundary.  In ``PERMANENT_LOCAL_ONLY`` mode every field stage returns
    blocked before any field validator or consumer is called.
    """
    try:
        matrix_snapshot = _clone_json_value(matrix, "$matrix")
        record_snapshot = _clone_json_value(record, "$record")
    except MatrixLoadError as error:
        issue = AcceptanceIssue(error.code, "$", str(error))
        return StageEvaluationResult(False, (issue,), ())
    validation = validate_matrix_definition(matrix_snapshot)
    if not validation.schema_valid:
        return StageEvaluationResult(False, validation.errors, ())
    if type(record_snapshot) is not dict:
        error = AcceptanceIssue(
            "TYPE_MISMATCH", "$record", "must be an exact object")
        return StageEvaluationResult(False, (error,), ())
    stage_id = record_snapshot.get("stage_id")
    stage = next(
        (item for item in matrix_snapshot["stages"]
         if item["id"] == stage_id),
        None,
    )
    if stage is None:
        error = AcceptanceIssue(
            "UNKNOWN_STAGE", "$record.stage_id", "stage is not allowed")
        return StageEvaluationResult(False, (error,), ())
    errors = _validate_record_structure(record_snapshot, matrix_snapshot, stage)
    if errors:
        return StageEvaluationResult(False, tuple(errors), ())

    blockers = []
    if (
            type(trusted_boundary_mode) is not str
            or trusted_boundary_mode not in BOUNDARY_MODES):
        _issue(
            blockers,
            "TRUSTED_BOUNDARY_REQUIRED",
            "$trusted_boundary_mode",
            "caller must provide an exact trusted boundary mode",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if type(trusted_policy_digest) is not str or SHA256_RE.fullmatch(
            trusted_policy_digest) is None:
        _issue(
            blockers,
            "TRUSTED_POLICY_DIGEST_REQUIRED",
            "$trusted_policy_digest",
            "caller must provide an exact lowercase SHA-256",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    actual_policy_digest = canonical_matrix_sha256(matrix_snapshot)
    if trusted_policy_digest != actual_policy_digest:
        _issue(
            blockers,
            "TRUSTED_POLICY_DIGEST_MISMATCH",
            "$trusted_policy_digest",
            "trusted policy digest does not bind the exact matrix",
        )
        return StageEvaluationResult(False, (), tuple(blockers))

    boundary = matrix_snapshot["current_task_boundary"]
    is_field = stage["kind"].startswith("FIELD_")
    if boundary["mode"] != trusted_boundary_mode:
        _issue(
            blockers,
            "TRUSTED_BOUNDARY_MISMATCH",
            "$.current_task_boundary.mode",
            "matrix boundary does not match caller-owned trusted policy",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if is_field and trusted_boundary_mode == "PERMANENT_LOCAL_ONLY":
        _issue(
            blockers,
            "PERMANENT_LOCAL_ONLY",
            "$.current_task_boundary.mode",
            "field stages are unconditionally blocked by the trusted boundary",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if is_field and trusted_boundary_mode != "FIELD_AUTHORIZED_POLICY":
        _issue(
            blockers,
            "FIELD_AUTHORIZED_BOUNDARY_REQUIRED",
            "$.current_task_boundary.mode",
            "field stages require the exact field-authorized boundary",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if (
            stage_id == "A1"
            and trusted_boundary_mode != "ROS1_NOETIC_FAKE_ONLY"):
        _issue(
            blockers,
            "A1_ROS1_FAKE_ONLY_BOUNDARY_REQUIRED",
            "$.current_task_boundary.mode",
            "A1 may execute only in the ROS1 Noetic fake-only boundary",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if stage["execution_permitted_in_current_task"] is not True:
        _issue(
            blockers,
            "CURRENT_TASK_BOUNDARY",
            "$.stages.{}".format(stage_id),
            "stage execution is prohibited by the current task boundary",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    if stage["current_disposition"] not in ("PASS_LOCAL", "ELIGIBLE"):
        _issue(
            blockers,
            "STAGE_NOT_ELIGIBLE",
            "$.stages.{}".format(stage_id),
            "current disposition cannot enter this stage",
        )
        return StageEvaluationResult(False, (), tuple(blockers))
    for permission in stage["required_boundary_permissions"]:
        if boundary[permission] is not True:
            _issue(
                blockers,
                "BOUNDARY_PERMISSION_MISSING",
                "$.current_task_boundary." + permission,
                "required permission is not exact true",
            )
    if blockers:
        return StageEvaluationResult(False, (), tuple(blockers))

    scope_sha = None
    authorization = record_snapshot["authorization"]
    if type(authorization) is dict:
        scope_sha = authorization["scope_sha256"]

    prerequisites = record_snapshot["completed_stage_evidence"]
    if is_field:
        stages_by_id = {
            item["id"]: item for item in matrix_snapshot["stages"]}
        for prerequisite_id in stage["prerequisites"]:
            prerequisite_stage = stages_by_id[prerequisite_id]
            if (
                    not prerequisite_stage["kind"].startswith("FIELD_")
                    and prerequisite_stage["current_disposition"]
                    != "PASS_LOCAL"):
                _issue(
                    blockers,
                    "OFFLINE_PREREQUISITE_NOT_COMPLETE",
                    "$.stages.{}".format(prerequisite_id),
                    "field entry requires offline prerequisite PASS_LOCAL",
                )
        if blockers:
            return StageEvaluationResult(False, (), tuple(blockers))
    if prerequisites and not is_field:
        stage_evidence_args = (
            stage_id,
            prerequisites,
            matrix_snapshot["matrix_revision"],
            trusted_policy_digest,
        )
        if not _call_validator(
                stage_evidence_validator,
                stage_evidence_args,
                "PREREQUISITE_AUTHORITY_UNVERIFIED",
                "$record.completed_stage_evidence",
                "prerequisite evidence authority did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    if not is_field:
        evidence_args = (
            stage_id,
            record_snapshot["required_evidence"],
            record_snapshot["session_id"],
            trusted_policy_digest,
        )
        if not _call_validator(
                evidence_validator,
                evidence_args,
                "OFFLINE_EVIDENCE_UNVERIFIED",
                "$record.required_evidence",
                "offline evidence did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))
        return StageEvaluationResult(True, (), ())

    release = matrix_snapshot["field_policy_release"]
    policy_args = (release, trusted_policy_digest)
    if not _call_validator(
            policy_authority_validator,
            policy_args,
            "FIELD_POLICY_AUTHORITY_UNVERIFIED",
            "$.field_policy_release",
            "external field-policy authority did not validate",
            blockers):
        return StageEvaluationResult(False, (), tuple(blockers))

    if prerequisites:
        stage_evidence_args = (
            stage_id,
            prerequisites,
            matrix_snapshot["matrix_revision"],
            trusted_policy_digest,
        )
        if not _call_validator(
                stage_evidence_validator,
                stage_evidence_args,
                "PREREQUISITE_AUTHORITY_UNVERIFIED",
                "$record.completed_stage_evidence",
                "prerequisite evidence authority did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    now_errors = []
    now = _utc_datetime(trusted_now_utc, "$trusted_now_utc", now_errors)
    if now_errors:
        return StageEvaluationResult(False, tuple(now_errors), ())
    not_before = _utc_datetime(
        authorization["not_before_utc"],
        "$record.authorization.not_before_utc", now_errors)
    expires = _utc_datetime(
        authorization["expires_at_utc"],
        "$record.authorization.expires_at_utc", now_errors)
    if now_errors:
        return StageEvaluationResult(False, tuple(now_errors), ())
    if now < not_before:
        _issue(
            blockers, "AUTHORIZATION_NOT_YET_VALID",
            "$record.authorization.not_before_utc",
            "trusted time is before the authorization window")
    if now >= expires:
        _issue(
            blockers, "AUTHORIZATION_EXPIRED",
            "$record.authorization.expires_at_utc",
            "trusted time is outside the authorization window")
    if blockers:
        return StageEvaluationResult(False, (), tuple(blockers))

    authorization_args = (
        authorization,
        scope_sha,
        trusted_policy_digest,
        record_snapshot,
    )
    if not _call_validator(
            authorization_authority_validator,
            authorization_args,
            "AUTHORIZATION_AUTHORITY_UNVERIFIED",
            "$record.authorization",
            "external one-time authorization did not validate",
            blockers):
        return StageEvaluationResult(False, (), tuple(blockers))

    binding_kind = stage["release_binding_kind"]
    binding = record_snapshot["release_binding"]
    if binding_kind != "NONE":
        release_args = (
            binding_kind,
            binding,
            record_snapshot["selected_speed_grade"],
            scope_sha,
            trusted_policy_digest,
        )
        if not _call_validator(
                release_binding_validator,
                release_args,
                "RELEASE_BINDING_AUTHORITY_UNVERIFIED",
                "$record.release_binding",
                "exact runtime release/profile binding did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    if stage["requires_independent_stop"]:
        transport_args = (
            binding_kind,
            record_snapshot["transport_capabilities"],
            binding,
            scope_sha,
            trusted_policy_digest,
        )
        if not _call_validator(
                transport_capability_validator,
                transport_args,
                "TRANSPORT_CAPABILITY_AUTHORITY_UNVERIFIED",
                "$record.transport_capabilities",
                "native deadlines/cancel and independent STOP did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    if stage["requires_persistent_latch"]:
        latch_args = (
            stage_id,
            record_snapshot["persistent_latch"],
            authorization,
            binding,
            scope_sha,
            trusted_policy_digest,
        )
        if not _call_validator(
                persistent_latch_validator,
                latch_args,
                "PERSISTENT_LATCH_UNVERIFIED",
                "$record.persistent_latch",
                "persistent latch/clearance did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    if stage["requires_physical_isolation"]:
        physical_args = (
            stage_id,
            record_snapshot["physical_isolation"],
            authorization,
            scope_sha,
            trusted_policy_digest,
        )
        if not _call_validator(
                physical_isolation_validator,
                physical_args,
                "PHYSICAL_ISOLATION_AUTHORITY_UNVERIFIED",
                "$record.physical_isolation",
                "physical isolation authority did not validate",
                blockers):
            return StageEvaluationResult(False, (), tuple(blockers))

    evidence_args = (
        stage_id,
        record_snapshot["required_evidence"],
        record_snapshot["session_id"],
        scope_sha,
        trusted_policy_digest,
    )
    if not _call_validator(
            evidence_validator,
            evidence_args,
            "FIELD_EVIDENCE_AUTHORITY_UNVERIFIED",
            "$record.required_evidence",
            "field evidence authority did not validate",
            blockers):
        return StageEvaluationResult(False, (), tuple(blockers))

    consumption_args = (
        authorization,
        scope_sha,
        record_snapshot,
        trusted_policy_digest,
        trusted_now_utc,
    )
    if not _call_validator(
            authorization_consumer,
            consumption_args,
            "AUTHORIZATION_NOT_ATOMICALLY_CONSUMED",
            "$record.authorization",
            "one-time authorization was not atomically consumed",
            blockers):
        return StageEvaluationResult(False, (), tuple(blockers))

    return StageEvaluationResult(True, (), ())


def main(argv=None):
    """Validate a matrix, or prove a record remains blocked locally."""
    parser = argparse.ArgumentParser(
        description="Validate the pure-local arm/gripper field contract")
    parser.add_argument("matrix")
    parser.add_argument("--record")
    parser.add_argument(
        "--trusted-boundary", choices=BOUNDARY_MODES,
        default="PERMANENT_LOCAL_ONLY")
    parser.add_argument("--trusted-policy-sha256")
    parser.add_argument("--trusted-now-utc")
    args = parser.parse_args(argv)
    try:
        matrix = load_matrix(args.matrix)
        if args.record is None:
            report = validate_matrix_definition(matrix).as_dict()
            exit_code = 0 if report["schema_valid"] else 2
        else:
            digest = args.trusted_policy_sha256 or canonical_matrix_sha256(
                matrix)
            result = evaluate_stage_entry(
                matrix,
                load_record(args.record),
                trusted_boundary_mode=args.trusted_boundary,
                trusted_policy_digest=digest,
                trusted_now_utc=args.trusted_now_utc,
            )
            report = result.as_dict()
            exit_code = 0 if result.allowed else 2
    except (MatrixLoadError, OSError, ValueError) as error:
        report = {
            "allowed": False,
            "errors": [{
                "code": getattr(error, "code", "VALIDATION_FAILED"),
                "path": "$",
                "message": str(error),
            }],
            "blockers": [],
        }
        exit_code = 2
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
