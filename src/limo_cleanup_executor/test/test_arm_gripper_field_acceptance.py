import ast
import hashlib
import json
import unittest
from pathlib import Path

from limo_cleanup_executor.arm_gripper_field_acceptance import (
    BOUNDARY_PERMISSION_KEYS,
    EXPECTED_STAGE_DEFINITIONS,
    MatrixLoadError,
    canonical_authorization_scope_sha256,
    canonical_matrix_payload_sha256,
    canonical_matrix_sha256,
    evaluate_stage_entry,
    load_matrix,
    loads_matrix,
    loads_record,
    validate_matrix_definition,
)


CONFIG = (
    Path(__file__).parents[1]
    / "config"
    / "arm_gripper_field_acceptance_matrix.json"
)
MODULE = (
    Path(__file__).parents[1]
    / "limo_cleanup_executor"
    / "arm_gripper_field_acceptance.py"
)
SETUP = Path(__file__).parents[1] / "setup.py"


def digest(character):
    return character * 64


def json_clone(value):
    return json.loads(json.dumps(value))


def set_record_path(record, path, value):
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def released_binding(prefix):
    return {
        "runtime_release_id": prefix + "-runtime-1",
        "release_manifest_sha256": digest(prefix.lower()),
        "profile_id": prefix + "-profile-1",
        "profile_manifest_sha256": digest(prefix.lower()),
        "profile_runtime_release_id": prefix + "-runtime-1",
        "approved_speed_grades": [1, 5],
        "bounded_call_artifact_sha256": digest("5"),
        "stop_isolation_artifact_sha256": digest("5"),
        "hung_command_stop_report_sha256": digest("6"),
    }


def make_ros1_noetic_matrix():
    matrix = load_matrix(CONFIG)
    matrix["matrix_revision"] = "ROS1-NOETIC-FAKE-ONLY-2026-08-14-R1"
    boundary = matrix["current_task_boundary"]
    boundary["mode"] = "ROS1_NOETIC_FAKE_ONLY"
    for key in BOUNDARY_PERMISSION_KEYS:
        boundary[key] = key == "ros_graph_allowed"
    for stage in matrix["stages"]:
        if stage["id"] == "A0":
            stage["current_disposition"] = "PASS_LOCAL"
            stage["execution_permitted_in_current_task"] = True
        elif stage["id"] == "A0-P":
            stage["current_disposition"] = "BLOCKED"
            stage["execution_permitted_in_current_task"] = True
        elif stage["id"] == "A1":
            stage["current_disposition"] = "ELIGIBLE"
            stage["execution_permitted_in_current_task"] = True
        elif stage["id"] in ("A2", "A3", "A4"):
            stage["current_disposition"] = "BLOCKED"
            stage["execution_permitted_in_current_task"] = False
        else:
            stage["current_disposition"] = "PROHIBITED"
            stage["execution_permitted_in_current_task"] = False
    assert validate_matrix_definition(matrix).schema_valid
    return matrix


def make_future_matrix():
    a1_completion_sha256 = make_a1_completion_sha256()
    matrix = load_matrix(CONFIG)
    matrix["matrix_revision"] = "FIELD-POLICY-2026-08-14-R1"
    boundary = matrix["current_task_boundary"]
    boundary["mode"] = "FIELD_AUTHORIZED_POLICY"
    for key in BOUNDARY_PERMISSION_KEYS:
        boundary[key] = False
    for key in (
            "field_activity_allowed",
            "device_access_allowed",
            "hardware_connection_allowed",
            "real_action_service_allowed",
            "motion_allowed"):
        boundary[key] = True
    matrix["field_policy_release"] = {
        "release_id": "FIELD-POLICY-RELEASE-1",
        "matrix_payload_sha256": None,
        "authority_evidence_sha256": a1_completion_sha256,
        "external_authority": True,
        "reviewed": True,
    }
    arm = released_binding("a")
    arm["release_manifest_sha256"] = digest("1")
    arm["profile_manifest_sha256"] = digest("2")
    gripper = released_binding("g")
    gripper["release_manifest_sha256"] = digest("3")
    gripper["profile_manifest_sha256"] = digest("4")
    gripper["bounded_call_artifact_sha256"] = digest("7")
    gripper["stop_isolation_artifact_sha256"] = digest("8")
    gripper["hung_command_stop_report_sha256"] = digest("9")
    matrix["expected_release_bindings"] = {
        "ARM": arm,
        "GRIPPER": gripper,
    }
    for stage in matrix["stages"]:
        if stage["id"] in ("A0", "A0-P", "A1"):
            stage["current_disposition"] = "PASS_LOCAL"
            stage["execution_permitted_in_current_task"] = False
        elif stage["kind"].startswith("FIELD_"):
            stage["current_disposition"] = "ELIGIBLE"
            stage["execution_permitted_in_current_task"] = True
    matrix["field_policy_release"]["matrix_payload_sha256"] = (
        canonical_matrix_payload_sha256(matrix))
    assert validate_matrix_definition(matrix).schema_valid
    return matrix


def make_transport(binding):
    return {
        "bounded_calls_enforced": True,
        "native_deadline_enforced": True,
        "native_cancel_enforced": True,
        "python_timeout_thread_used": False,
        "independent_stop_channel": True,
        "independent_stop_lock_domain": True,
        "stop_not_queued_behind_commands": True,
        "hung_send_stop_completed_before_send_release": True,
        "persistent_physical_isolation_latch": True,
        "command_channel_id": "motion-channel",
        "stop_channel_id": "stop-channel",
        "command_lock_domain_id": "motion-lock",
        "stop_lock_domain_id": "stop-lock",
        "method_deadlines_s": {
            "read_state": 0.5,
            "command": 0.5,
            "stop": 0.2,
            "close": 0.5,
        },
        "bounded_call_artifact_sha256": binding[
            "bounded_call_artifact_sha256"],
        "stop_isolation_artifact_sha256": binding[
            "stop_isolation_artifact_sha256"],
        "hung_command_stop_report_sha256": binding[
            "hung_command_stop_report_sha256"],
        "unresolved_stop_escalation": (
            "PERSISTENT_PHYSICAL_ISOLATION_REQUIRED"),
    }


def stage_from(matrix, stage_id):
    return next(stage for stage in matrix["stages"] if stage["id"] == stage_id)


def make_record(matrix, stage_id):
    stage = stage_from(matrix, stage_id)
    binding_kind = stage["release_binding_kind"]
    binding = (
        json_clone(matrix["expected_release_bindings"][binding_kind])
        if binding_kind != "NONE" else None)
    latch_snapshot = digest("7") if stage["requires_persistent_latch"] else None
    physical_isolation_sha = (
        digest("e") if stage["requires_physical_isolation"] else None)
    command_id = "command-1" if stage["motion_stage"] else None
    authorization = None
    if stage["one_time_authorization"]:
        authorization = {
            "authorization_id": "authorization-" + stage_id,
            "external_authority": True,
            "authority_evidence_sha256": digest("8"),
            "scope": stage["authorization_scope"],
            "session_id": "session-1",
            "operation_id": "operation-1",
            "issued_at_utc": "2026-08-14T00:00:00Z",
            "not_before_utc": "2026-08-14T00:01:00Z",
            "expires_at_utc": "2026-08-14T00:10:00Z",
            "one_time": True,
            "max_uses": 1,
            "scope_sha256": digest("0"),
            "credential_sha256": digest("9"),
            "clearance_id": (
                "clearance-1" if stage["requires_persistent_latch"]
                else None),
            "latch_snapshot_sha256": latch_snapshot,
            "command_id": command_id,
        }
    transport = (
        make_transport(binding) if stage["requires_independent_stop"] else None)
    latch = None
    if stage["requires_persistent_latch"]:
        latch = {
            "store_id": "latch-store-1",
            "status": "CLEAR",
            "generation": 7,
            "clearance_id": authorization["clearance_id"],
            "latched_session_epoch": 6,
            "clearing_session_epoch": 7,
            "record_sha256": digest("b"),
            "snapshot_sha256": latch_snapshot,
            "session_binding_sha256": digest("c"),
            "runtime_release_id": binding["runtime_release_id"],
            "release_manifest_sha256": binding["release_manifest_sha256"],
            "profile_id": binding["profile_id"],
            "profile_manifest_sha256": binding["profile_manifest_sha256"],
            "external_clearance_validator_required": True,
            "protected_authority_evidence_sha256": digest("d"),
            "bounded_call_artifact_sha256": binding[
                "bounded_call_artifact_sha256"],
            "stop_isolation_artifact_sha256": binding[
                "stop_isolation_artifact_sha256"],
            "hung_command_stop_report_sha256": binding[
                "hung_command_stop_report_sha256"],
            "physical_isolation_evidence_sha256": physical_isolation_sha,
            "approval_artifact_sha256": authorization[
                "authority_evidence_sha256"],
        }
    isolation = None
    if stage["requires_physical_isolation"]:
        isolation = {
            "verified": True,
            "zero_energy_verified": True,
            "physical_estop_verified": True,
            "evidence_sha256": physical_isolation_sha,
        }
    def prerequisite_digest(prerequisite):
        if (
                prerequisite == "A1"
                and matrix["current_task_boundary"]["mode"]
                == "FIELD_AUTHORIZED_POLICY"):
            return matrix["field_policy_release"][
                "authority_evidence_sha256"]
        return digest("f")

    record = {
        "schema_id": "limo.arm_gripper_stage_entry_record",
        "schema_version": 1,
        "record_id": "record-" + stage_id,
        "matrix_revision": matrix["matrix_revision"],
        "stage_id": stage_id,
        "operation": stage["operation"],
        "session_id": "session-1",
        "operation_id": "operation-1",
        "completed_stage_evidence": {
            prerequisite: prerequisite_digest(prerequisite)
            for prerequisite in stage["prerequisites"]
        },
        "authorization": authorization,
        "release_binding": binding,
        "selected_speed_grade": (
            binding["approved_speed_grades"][0]
            if stage["motion_stage"] else None),
        "transport_capabilities": transport,
        "persistent_latch": latch,
        "physical_isolation": isolation,
        "required_evidence": {
            key: digest("a") for key in stage["required_evidence_keys"]
        },
    }
    if authorization is not None:
        authorization["scope_sha256"] = canonical_authorization_scope_sha256(
            matrix, record)
    return record


def make_a1_completion_sha256():
    """Produce a structured test-only A1 completion under the Noetic boundary."""
    matrix = make_ros1_noetic_matrix()
    record = make_record(matrix, "A1")
    policy_sha256 = canonical_matrix_sha256(matrix)
    expected_evidence = {
        key: hashlib.sha256(
            ("test-a1-evidence:" + key).encode("utf-8")).hexdigest()
        for key in EXPECTED_STAGE_DEFINITIONS["A1"][
            "required_evidence_keys"]
    }
    record["required_evidence"] = expected_evidence

    def validate_prerequisite(
            stage_id, completed, matrix_revision, trusted_policy_sha256):
        return (
            stage_id == "A1"
            and completed == {"A0": digest("f")}
            and matrix_revision == matrix["matrix_revision"]
            and trusted_policy_sha256 == policy_sha256
        )

    def validate_required_evidence(
            stage_id, evidence, session_id, trusted_policy_sha256):
        return (
            stage_id == "A1"
            and evidence == expected_evidence
            and session_id == record["session_id"]
            and trusted_policy_sha256 == policy_sha256
        )

    result = evaluate_stage_entry(
        matrix,
        record,
        trusted_boundary_mode="ROS1_NOETIC_FAKE_ONLY",
        trusted_policy_digest=policy_sha256,
        stage_evidence_validator=validate_prerequisite,
        evidence_validator=validate_required_evidence,
    )
    if not result.allowed:
        raise AssertionError(result.as_dict())
    payload = {
        "schema_id": "test.ros1_noetic_a1_completion",
        "matrix_sha256": policy_sha256,
        "record": record,
        "result": result.as_dict(),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def exact_true(*unused_args):
    return True


def all_callbacks(**overrides):
    callbacks = {
        "policy_authority_validator": exact_true,
        "stage_evidence_validator": exact_true,
        "authorization_authority_validator": exact_true,
        "release_binding_validator": exact_true,
        "transport_capability_validator": exact_true,
        "persistent_latch_validator": exact_true,
        "physical_isolation_validator": exact_true,
        "evidence_validator": exact_true,
        "authorization_consumer": exact_true,
    }
    callbacks.update(overrides)
    return callbacks


def evaluate_future(matrix, record, **overrides):
    callbacks = all_callbacks(**overrides)
    return evaluate_stage_entry(
        matrix,
        record,
        trusted_boundary_mode="FIELD_AUTHORIZED_POLICY",
        trusted_policy_digest=canonical_matrix_sha256(matrix),
        trusted_now_utc="2026-08-14T00:05:00Z",
        **callbacks
    )


def resign_authorization_scope(matrix, record):
    record["authorization"]["scope_sha256"] = (
        canonical_authorization_scope_sha256(matrix, record))


class FieldAcceptanceContractTest(unittest.TestCase):
    def assert_scope_mutation_rejected(self, matrix, path, value):
        record = make_record(matrix, "A5-A")
        stale_scope = record["authorization"]["scope_sha256"]
        set_record_path(record, path, value)
        self.assertNotEqual(
            stale_scope,
            canonical_authorization_scope_sha256(matrix, record),
            path,
        )
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed, path)
        self.assertIn(
            "AUTHORIZATION_SCOPE_HASH_MISMATCH",
            {issue.code for issue in result.errors},
            path,
        )

    def test_verifier_is_python38_and_runtime_inert(self):
        source = MODULE.read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 8))
        forbidden = (
            "import rclpy", "import serial", "import pymycobot",
            "import socket", "import subprocess", "paramiko", "ros2 ",
            "/dev/", "\\\\.\\", "create_client(", "create_publisher(",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_setup_installs_matrix_and_local_verifier(self):
        setup_source = SETUP.read_text(encoding="utf-8")
        self.assertIn("arm_gripper_field_acceptance_matrix.json", setup_source)
        self.assertIn("verify_arm_gripper_field_acceptance", setup_source)

    def test_local_matrix_is_strict_and_valid(self):
        matrix = load_matrix(CONFIG)
        result = validate_matrix_definition(matrix)
        self.assertTrue(result.schema_valid, result.as_dict())
        self.assertEqual("PERMANENT_LOCAL_ONLY", matrix["current_task_boundary"]["mode"])
        self.assertFalse(matrix["field_policy_release"]["external_authority"])

    def test_ros1_noetic_boundary_allows_only_isolated_fake_graph(self):
        matrix = make_ros1_noetic_matrix()
        boundary = matrix["current_task_boundary"]
        self.assertEqual("ROS1_NOETIC_FAKE_ONLY", boundary["mode"])
        self.assertTrue(boundary["ros_graph_allowed"])
        self.assertTrue(all(
            boundary[key] is False
            for key in BOUNDARY_PERMISSION_KEYS
            if key != "ros_graph_allowed"
        ))
        self.assertFalse(matrix["field_policy_release"]["external_authority"])
        self.assertIsNone(matrix["expected_release_bindings"]["ARM"])
        self.assertIsNone(matrix["expected_release_bindings"]["GRIPPER"])

        record = make_record(matrix, "A1")
        policy_sha256 = canonical_matrix_sha256(matrix)
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="ROS1_NOETIC_FAKE_ONLY",
            trusted_policy_digest=policy_sha256,
            stage_evidence_validator=lambda *unused: True,
            evidence_validator=lambda *unused: True,
        )
        self.assertTrue(result.allowed, result.as_dict())

    def test_ros1_noetic_boundary_never_admits_field_stage(self):
        matrix = make_ros1_noetic_matrix()
        record = make_record(matrix, "A2")
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="ROS1_NOETIC_FAKE_ONLY",
            trusted_policy_digest=canonical_matrix_sha256(matrix),
            **all_callbacks()
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            "FIELD_AUTHORIZED_BOUNDARY_REQUIRED", result.blockers[0].code)

    def test_field_stage_pass_local_disposition_is_rejected(self):
        matrix = make_future_matrix()
        stage_from(matrix, "A2")["current_disposition"] = "PASS_LOCAL"
        matrix["field_policy_release"]["matrix_payload_sha256"] = (
            canonical_matrix_payload_sha256(matrix))
        result = validate_matrix_definition(matrix)
        self.assertFalse(result.schema_valid)
        self.assertIn(
            "FIELD_STAGE_STATE_INVALID",
            {issue.code for issue in result.errors},
        )

    def test_required_field_stage_cannot_use_skipped_as_pass(self):
        matrix = make_future_matrix()
        stage_from(matrix, "A2")["current_disposition"] = "SKIPPED"
        stage_from(matrix, "A2")["execution_permitted_in_current_task"] = False
        matrix["field_policy_release"]["matrix_payload_sha256"] = (
            canonical_matrix_payload_sha256(matrix))
        result = validate_matrix_definition(matrix)
        self.assertFalse(result.schema_valid)
        self.assertIn(
            "INVALID_DISPOSITION",
            {issue.code for issue in result.errors},
        )

    def test_exact_true_callback_cannot_bypass_unfinished_a1(self):
        matrix = make_future_matrix()
        a1 = stage_from(matrix, "A1")
        a1["current_disposition"] = "BLOCKED"
        a1["execution_permitted_in_current_task"] = False
        matrix["field_policy_release"]["matrix_payload_sha256"] = (
            canonical_matrix_payload_sha256(matrix))
        record = make_record(matrix, "A2")
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="FIELD_AUTHORIZED_POLICY",
            trusted_policy_digest=canonical_matrix_sha256(matrix),
            trusted_now_utc="2026-08-14T00:05:00Z",
            **all_callbacks()
        )
        self.assertFalse(result.allowed)
        self.assertIn(
            "FIELD_OFFLINE_PREREQUISITE_NOT_COMPLETE",
            {issue.code for issue in result.errors},
        )

    def test_future_field_helper_uses_prior_noetic_a1_completion(self):
        completion_sha256 = make_a1_completion_sha256()
        matrix = make_future_matrix()
        a1 = stage_from(matrix, "A1")
        self.assertEqual("FIELD_AUTHORIZED_POLICY", matrix[
            "current_task_boundary"]["mode"])
        self.assertFalse(matrix["current_task_boundary"]["ros_graph_allowed"])
        self.assertEqual("PASS_LOCAL", a1["current_disposition"])
        self.assertFalse(a1["execution_permitted_in_current_task"])
        self.assertEqual(
            completion_sha256,
            matrix["field_policy_release"]["authority_evidence_sha256"],
        )
        record = make_record(matrix, "A2")
        self.assertEqual(
            completion_sha256,
            record["completed_stage_evidence"]["A1"],
        )

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        with self.assertRaisesRegex(MatrixLoadError, "duplicate"):
            loads_matrix('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(MatrixLoadError, "non-finite"):
            loads_record('{"value":NaN}')

    def test_active_python_object_is_rejected_without_deepcopy_hook(self):
        class ActiveValue:
            def __init__(self):
                self.called = False

            def __deepcopy__(self, unused_memo):
                self.called = True
                raise AssertionError("must not execute")

        active = ActiveValue()
        matrix = load_matrix(CONFIG)
        matrix["matrix_revision"] = active
        result = validate_matrix_definition(matrix)
        self.assertFalse(result.schema_valid)
        self.assertFalse(active.called)

    def test_permanent_local_only_blocks_field_before_any_callback(self):
        matrix = load_matrix(CONFIG)
        record = make_record(matrix, "A2")

        def forbidden(*unused_args):
            raise AssertionError("field callback must not run")

        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="PERMANENT_LOCAL_ONLY",
            trusted_policy_digest=canonical_matrix_sha256(matrix),
            trusted_now_utc=None,
            policy_authority_validator=forbidden,
            stage_evidence_validator=forbidden,
            authorization_authority_validator=forbidden,
            release_binding_validator=forbidden,
            transport_capability_validator=forbidden,
            persistent_latch_validator=forbidden,
            physical_isolation_validator=forbidden,
            evidence_validator=forbidden,
            authorization_consumer=forbidden,
        )
        self.assertFalse(result.allowed)
        self.assertEqual("PERMANENT_LOCAL_ONLY", result.blockers[0].code)

    def test_matrix_cannot_override_caller_owned_local_boundary(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A2")
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="PERMANENT_LOCAL_ONLY",
            trusted_policy_digest=canonical_matrix_sha256(matrix),
        )
        self.assertFalse(result.allowed)
        self.assertEqual("TRUSTED_BOUNDARY_MISMATCH", result.blockers[0].code)

    def test_trusted_policy_digest_is_exact_and_required(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A2")
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode="FIELD_AUTHORIZED_POLICY",
            trusted_policy_digest=digest("0"),
        )
        self.assertEqual("TRUSTED_POLICY_DIGEST_MISMATCH", result.blockers[0].code)

    def test_trusted_boundary_rejects_active_string_subclass(self):
        class ActiveString(str):
            def __new__(cls):
                value = super().__new__(cls, "FIELD_AUTHORIZED_POLICY")
                value.called = False
                return value

            def __eq__(self, unused_other):
                self.called = True
                raise AssertionError("must not compare active boundary")

        matrix = make_future_matrix()
        record = make_record(matrix, "A2")
        mode = ActiveString()
        result = evaluate_stage_entry(
            matrix,
            record,
            trusted_boundary_mode=mode,
            trusted_policy_digest=canonical_matrix_sha256(matrix),
        )
        self.assertFalse(result.allowed)
        self.assertEqual("TRUSTED_BOUNDARY_REQUIRED", result.blockers[0].code)
        self.assertFalse(mode.called)

    def test_a2_static_calls_only_relevant_exact_authorities(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A2")
        calls = []

        def accepted(name):
            def callback(*unused_args):
                calls.append(name)
                return True
            return callback

        def forbidden(*unused_args):
            raise AssertionError("A2 must not invoke motion/backend/latch gates")

        result = evaluate_future(
            matrix,
            record,
            policy_authority_validator=accepted("policy"),
            stage_evidence_validator=accepted("prerequisite"),
            authorization_authority_validator=accepted("authorization"),
            release_binding_validator=forbidden,
            transport_capability_validator=forbidden,
            persistent_latch_validator=forbidden,
            physical_isolation_validator=accepted("physical"),
            evidence_validator=accepted("evidence"),
            authorization_consumer=accepted("consume"),
        )
        self.assertTrue(result.allowed, result.as_dict())
        self.assertEqual(
            ["policy", "prerequisite", "authorization", "physical",
             "evidence", "consume"], calls)

    def test_a5_siblings_are_independent_and_not_prerequisites(self):
        matrix = make_future_matrix()
        arm = stage_from(matrix, "A5-A")
        gripper = stage_from(matrix, "A5-G")
        self.assertNotIn("A5-G", arm["prerequisites"])
        self.assertNotIn("A5-A", gripper["prerequisites"])
        self.assertNotEqual(arm["authorization_scope"], gripper["authorization_scope"])
        record = make_record(matrix, "A5-G")
        record["authorization"]["scope"] = arm["authorization_scope"]
        record["authorization"]["scope_sha256"] = (
            canonical_authorization_scope_sha256(matrix, record))
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed)
        self.assertIn(
            "AUTHORIZATION_SCOPE_MISMATCH",
            {issue.code for issue in result.errors})

    def test_full_a5_contract_passes_only_with_all_exact_true_callbacks(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        result = evaluate_future(matrix, record)
        self.assertTrue(result.allowed, result.as_dict())

    def test_truthy_callback_value_is_not_external_authority(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        result = evaluate_future(
            matrix,
            record,
            authorization_authority_validator=lambda *unused_args: 1,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            "AUTHORIZATION_AUTHORITY_UNVERIFIED", result.blockers[0].code)

    def test_fresh_resign_cannot_forge_external_authority_evidence(self):
        matrix = make_future_matrix()
        cases = ("credential_sha256", "authority_evidence_sha256")
        for field in cases:
            with self.subTest(field=field):
                record = make_record(matrix, "A5-A")
                trusted_sha = record["authorization"][field]
                record["authorization"][field] = digest("0")
                if field == "authority_evidence_sha256":
                    record["persistent_latch"][
                        "approval_artifact_sha256"] = digest("0")
                resign_authorization_scope(matrix, record)

                def validate_authority(authorization, *unused_args):
                    return authorization[field] == trusted_sha

                result = evaluate_future(
                    matrix,
                    record,
                    authorization_authority_validator=validate_authority,
                )
                self.assertFalse(result.allowed)
                self.assertEqual(
                    "AUTHORIZATION_AUTHORITY_UNVERIFIED",
                    result.blockers[0].code,
                )

    def test_each_bound_authority_is_mandatory_and_exact_true(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        cases = (
            ("release_binding_validator", "RELEASE_BINDING_AUTHORITY_UNVERIFIED"),
            ("transport_capability_validator", "TRANSPORT_CAPABILITY_AUTHORITY_UNVERIFIED"),
            ("persistent_latch_validator", "PERSISTENT_LATCH_UNVERIFIED"),
            ("physical_isolation_validator", "PHYSICAL_ISOLATION_AUTHORITY_UNVERIFIED"),
            ("evidence_validator", "FIELD_EVIDENCE_AUTHORITY_UNVERIFIED"),
            ("authorization_consumer", "AUTHORIZATION_NOT_ATOMICALLY_CONSUMED"),
        )
        for callback_name, code in cases:
            with self.subTest(callback=callback_name):
                result = evaluate_future(
                    matrix, record, **{callback_name: lambda *args: False})
                self.assertFalse(result.allowed)
                self.assertEqual(code, result.blockers[0].code)

    def test_authorization_requires_exact_external_true_and_max_uses_one(self):
        matrix = make_future_matrix()
        for key, value, code in (
                ("external_authority", 1, "INVALID_BOOLEAN"),
                ("external_authority", False, "EXTERNAL_AUTHORITY_REQUIRED"),
                ("max_uses", True, "INVALID_INTEGER"),
                ("max_uses", 2, "INTEGER_OUT_OF_RANGE"),
                ("one_time", 1, "AUTHORIZATION_NOT_ONE_TIME")):
            with self.subTest(key=key, value=value):
                record = make_record(matrix, "A2")
                record["authorization"][key] = value
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(code, {issue.code for issue in result.errors})

    def test_authorization_utc_window_is_strict(self):
        matrix = make_future_matrix()
        invalid = make_record(matrix, "A2")
        invalid["authorization"]["expires_at_utc"] = "2026-08-14 00:10:00"
        result = evaluate_future(matrix, invalid)
        self.assertIn("INVALID_UTC_TIMESTAMP", {i.code for i in result.errors})

        expired = make_record(matrix, "A2")
        result = evaluate_stage_entry(
            matrix,
            expired,
            trusted_boundary_mode="FIELD_AUTHORIZED_POLICY",
            trusted_policy_digest=canonical_matrix_sha256(matrix),
            trusted_now_utc="2026-08-14T00:10:00Z",
            **all_callbacks()
        )
        self.assertFalse(result.allowed)
        self.assertEqual("AUTHORIZATION_EXPIRED", result.blockers[0].code)

    def test_scope_hash_binds_release_transport_latch_and_isolation(self):
        matrix = make_future_matrix()
        mutations = (
            ("expiry", lambda record: record["authorization"].update(
                {"expires_at_utc": "2026-08-14T00:20:00Z"})),
            ("prerequisite", lambda record: record[
                "completed_stage_evidence"].update({"A0": digest("0")})),
            ("release", lambda record: record["release_binding"].update(
                {"runtime_release_id": "stale-runtime"})),
            ("transport", lambda record: record["transport_capabilities"].update(
                {"bounded_call_artifact_sha256": digest("0")})),
            ("latch", lambda record: record["persistent_latch"].update(
                {"snapshot_sha256": digest("0")})),
            ("isolation", lambda record: record["physical_isolation"].update(
                {"evidence_sha256": digest("0")})),
            ("evidence", lambda record: record["required_evidence"].update(
                {"first_motion_plan_sha256": digest("0")})),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                record = make_record(matrix, "A5-A")
                mutate(record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(
                    "AUTHORIZATION_SCOPE_HASH_MISMATCH",
                    {issue.code for issue in result.errors})

    def test_scope_hash_binds_every_transport_capability_field(self):
        matrix = make_future_matrix()
        cases = (
            (("transport_capabilities", "bounded_calls_enforced"), False),
            (("transport_capabilities", "native_deadline_enforced"), False),
            (("transport_capabilities", "native_cancel_enforced"), False),
            (("transport_capabilities", "python_timeout_thread_used"), True),
            (("transport_capabilities", "independent_stop_channel"), False),
            (("transport_capabilities", "independent_stop_lock_domain"), False),
            (("transport_capabilities", "stop_not_queued_behind_commands"), False),
            (("transport_capabilities", "hung_send_stop_completed_before_send_release"), False),
            (("transport_capabilities", "persistent_physical_isolation_latch"), False),
            (("transport_capabilities", "command_channel_id"), "motion-channel-v2"),
            (("transport_capabilities", "stop_channel_id"), "stop-channel-v2"),
            (("transport_capabilities", "command_lock_domain_id"), "motion-lock-v2"),
            (("transport_capabilities", "stop_lock_domain_id"), "stop-lock-v2"),
            (("transport_capabilities", "method_deadlines_s", "read_state"), 0.6),
            (("transport_capabilities", "method_deadlines_s", "command"), 0.6),
            (("transport_capabilities", "method_deadlines_s", "stop"), 0.3),
            (("transport_capabilities", "method_deadlines_s", "close"), 0.6),
            (("transport_capabilities", "bounded_call_artifact_sha256"), digest("0")),
            (("transport_capabilities", "stop_isolation_artifact_sha256"), digest("1")),
            (("transport_capabilities", "hung_command_stop_report_sha256"), digest("1")),
            (("transport_capabilities", "unresolved_stop_escalation"), "BLOCKED"),
            (("transport_capabilities", "unexpected_capability"), True),
        )
        for path, value in cases:
            with self.subTest(path=path):
                self.assert_scope_mutation_rejected(matrix, path, value)

    def test_scope_hash_binds_every_authorization_field_except_self_hash(self):
        matrix = make_future_matrix()
        cases = (
            (("authorization", "authorization_id"), "authorization-v2"),
            (("authorization", "external_authority"), False),
            (("authorization", "authority_evidence_sha256"), digest("0")),
            (("authorization", "scope"), "A5_G_GRIPPER_FIRST_MOTION"),
            (("authorization", "session_id"), "session-2"),
            (("authorization", "operation_id"), "operation-2"),
            (("authorization", "issued_at_utc"), "2026-08-13T23:59:00Z"),
            (("authorization", "not_before_utc"), "2026-08-14T00:02:00Z"),
            (("authorization", "expires_at_utc"), "2026-08-14T00:09:00Z"),
            (("authorization", "one_time"), False),
            (("authorization", "max_uses"), 2),
            (("authorization", "credential_sha256"), digest("0")),
            (("authorization", "clearance_id"), "clearance-2"),
            (("authorization", "latch_snapshot_sha256"), digest("0")),
            (("authorization", "command_id"), "command-2"),
            (("authorization", "unexpected_authorization_field"), True),
        )
        for path, value in cases:
            with self.subTest(path=path):
                self.assert_scope_mutation_rejected(matrix, path, value)

    def test_scope_hash_normalizes_only_its_own_authorization_field(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        expected = record["authorization"]["scope_sha256"]
        record["authorization"]["scope_sha256"] = digest("1")
        self.assertEqual(
            expected, canonical_authorization_scope_sha256(matrix, record))
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed)
        self.assertIn(
            "AUTHORIZATION_SCOPE_HASH_MISMATCH",
            {issue.code for issue in result.errors},
        )

    def test_scope_hash_binds_every_persistent_latch_field(self):
        matrix = make_future_matrix()
        cases = (
            (("persistent_latch", "store_id"), "latch-store-2"),
            (("persistent_latch", "status"), "ACTIVE"),
            (("persistent_latch", "generation"), 8),
            (("persistent_latch", "clearance_id"), "clearance-2"),
            (("persistent_latch", "latched_session_epoch"), 5),
            (("persistent_latch", "clearing_session_epoch"), 8),
            (("persistent_latch", "record_sha256"), digest("0")),
            (("persistent_latch", "snapshot_sha256"), digest("1")),
            (("persistent_latch", "session_binding_sha256"), digest("2")),
            (("persistent_latch", "runtime_release_id"), "stale-runtime"),
            (("persistent_latch", "release_manifest_sha256"), digest("5")),
            (("persistent_latch", "profile_id"), "stale-profile"),
            (("persistent_latch", "profile_manifest_sha256"), digest("6")),
            (("persistent_latch", "external_clearance_validator_required"), False),
            (("persistent_latch", "protected_authority_evidence_sha256"), digest("0")),
            (("persistent_latch", "bounded_call_artifact_sha256"), digest("3")),
            (("persistent_latch", "stop_isolation_artifact_sha256"), digest("4")),
            (("persistent_latch", "hung_command_stop_report_sha256"), digest("5")),
            (("persistent_latch", "physical_isolation_evidence_sha256"), digest("1")),
            (("persistent_latch", "approval_artifact_sha256"), digest("2")),
            (("persistent_latch", "unexpected_latch_field"), "forbidden"),
        )
        for path, value in cases:
            with self.subTest(path=path):
                self.assert_scope_mutation_rejected(matrix, path, value)

    def test_scope_hash_binds_every_physical_isolation_field(self):
        matrix = make_future_matrix()
        cases = (
            (("physical_isolation", "verified"), False),
            (("physical_isolation", "zero_energy_verified"), False),
            (("physical_isolation", "physical_estop_verified"), False),
            (("physical_isolation", "evidence_sha256"), digest("0")),
            (("physical_isolation", "unexpected_isolation_field"), True),
        )
        for path, value in cases:
            with self.subTest(path=path):
                self.assert_scope_mutation_rejected(matrix, path, value)

    def test_valid_safety_field_mutations_are_stopped_by_scope_hash(self):
        matrix = make_future_matrix()
        cases = (
            (("transport_capabilities", "method_deadlines_s", "stop"), 0.3),
            (("transport_capabilities", "command_channel_id"), "motion-channel-v2"),
            (("transport_capabilities", "stop_channel_id"), "stop-channel-v2"),
            (("transport_capabilities", "command_lock_domain_id"), "motion-lock-v2"),
            (("transport_capabilities", "stop_lock_domain_id"), "stop-lock-v2"),
            (("persistent_latch", "generation"), 8),
            (("persistent_latch", "record_sha256"), digest("0")),
        )
        for path, value in cases:
            with self.subTest(path=path):
                record = make_record(matrix, "A5-A")
                set_record_path(record, path, value)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertEqual(
                    {"AUTHORIZATION_SCOPE_HASH_MISMATCH"},
                    {issue.code for issue in result.errors},
                )

    def test_resigned_transport_evidence_must_match_approved_binding(self):
        matrix = make_future_matrix()
        cases = (
            (
                "bounded_call_artifact_sha256",
                "TRANSPORT_BOUNDED_CALL_EVIDENCE_BINDING_MISMATCH",
            ),
            (
                "stop_isolation_artifact_sha256",
                "TRANSPORT_STOP_ISOLATION_EVIDENCE_BINDING_MISMATCH",
            ),
            (
                "hung_command_stop_report_sha256",
                "TRANSPORT_HUNG_STOP_EVIDENCE_BINDING_MISMATCH",
            ),
        )
        for field, code in cases:
            with self.subTest(field=field):
                record = make_record(matrix, "A5-A")
                record["transport_capabilities"][field] = digest("0")
                resign_authorization_scope(matrix, record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(code, {issue.code for issue in result.errors})

    def test_only_arm_bounded_and_stop_evidence_may_share_a_hash(self):
        roles = (
            "release_manifest_sha256",
            "profile_manifest_sha256",
            "bounded_call_artifact_sha256",
            "stop_isolation_artifact_sha256",
            "hung_command_stop_report_sha256",
        )
        allowed_arm_pair = frozenset((
            "bounded_call_artifact_sha256",
            "stop_isolation_artifact_sha256",
        ))
        for binding_kind in ("ARM", "GRIPPER"):
            for left_index, left_role in enumerate(roles):
                for right_role in roles[left_index + 1:]:
                    role_pair = frozenset((left_role, right_role))
                    if binding_kind == "ARM" and role_pair == allowed_arm_pair:
                        continue
                    with self.subTest(
                            binding_kind=binding_kind,
                            left=left_role,
                            right=right_role):
                        matrix = make_future_matrix()
                        binding = matrix["expected_release_bindings"][
                            binding_kind]
                        binding[right_role] = binding[left_role]
                        matrix["field_policy_release"][
                            "matrix_payload_sha256"] = (
                                canonical_matrix_payload_sha256(matrix))
                        result = validate_matrix_definition(matrix)
                        self.assertFalse(result.schema_valid)
                        self.assertIn(
                            "BINDING_HASH_REUSE",
                            {issue.code for issue in result.errors},
                        )

    def test_resigned_latch_evidence_must_match_release_and_transport(self):
        matrix = make_future_matrix()
        cases = (
            (
                "bounded_call_artifact_sha256",
                "LATCH_BOUNDED_CALL_EVIDENCE_BINDING_MISMATCH",
            ),
            (
                "stop_isolation_artifact_sha256",
                "LATCH_STOP_ISOLATION_EVIDENCE_BINDING_MISMATCH",
            ),
            (
                "hung_command_stop_report_sha256",
                "LATCH_HUNG_STOP_EVIDENCE_BINDING_MISMATCH",
            ),
        )
        for field, code in cases:
            with self.subTest(field=field):
                record = make_record(matrix, "A5-A")
                record["persistent_latch"][field] = digest("0")
                resign_authorization_scope(matrix, record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(code, {issue.code for issue in result.errors})

    def test_resigned_coordinated_evidence_substitution_stays_blocked(self):
        matrix = make_future_matrix()
        for field in (
                "bounded_call_artifact_sha256",
                "stop_isolation_artifact_sha256",
                "hung_command_stop_report_sha256"):
            with self.subTest(field=field):
                record = make_record(matrix, "A5-A")
                replacement = digest("0")
                record["release_binding"][field] = replacement
                record["transport_capabilities"][field] = replacement
                record["persistent_latch"][field] = replacement
                resign_authorization_scope(matrix, record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(
                    "RELEASE_BINDING_MISMATCH",
                    {issue.code for issue in result.errors},
                )

    def test_scope_hash_uses_canonical_object_key_order(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        expected = record["authorization"]["scope_sha256"]
        for key in (
                "authorization", "transport_capabilities", "persistent_latch",
                "physical_isolation"):
            value = record[key]
            record[key] = {
                item_key: value[item_key]
                for item_key in reversed(tuple(value))
            }
        deadlines = record["transport_capabilities"]["method_deadlines_s"]
        record["transport_capabilities"]["method_deadlines_s"] = {
            key: deadlines[key] for key in reversed(tuple(deadlines))
        }
        self.assertEqual(
            expected, canonical_authorization_scope_sha256(matrix, record))

    def test_motion_speed_grade_must_be_exact_and_approved(self):
        matrix = make_future_matrix()
        for value in (True, 2, 101):
            with self.subTest(value=value):
                record = make_record(matrix, "A5-A")
                record["selected_speed_grade"] = value
                record["authorization"]["scope_sha256"] = (
                    canonical_authorization_scope_sha256(matrix, record))
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                codes = {issue.code for issue in result.errors}
                self.assertTrue(
                    "INVALID_INTEGER" in codes
                    or "INTEGER_OUT_OF_RANGE" in codes
                    or "SPEED_GRADE_NOT_APPROVED" in codes)

    def test_timeout_thread_and_shared_stop_domains_fail_closed(self):
        matrix = make_future_matrix()
        cases = (
            ("python_timeout_thread_used", True, "PYTHON_TIMEOUT_THREAD_FORBIDDEN"),
            ("stop_not_queued_behind_commands", False, "CAPABILITY_NOT_PROVEN"),
            ("independent_stop_channel", False, "CAPABILITY_NOT_PROVEN"),
        )
        for key, value, code in cases:
            with self.subTest(key=key):
                record = make_record(matrix, "A5-A")
                record["transport_capabilities"][key] = value
                result = evaluate_future(matrix, record)
                self.assertIn(code, {issue.code for issue in result.errors})

        shared = make_record(matrix, "A5-A")
        shared["transport_capabilities"]["stop_channel_id"] = "motion-channel"
        result = evaluate_future(matrix, shared)
        self.assertIn("STOP_CHANNEL_NOT_INDEPENDENT", {i.code for i in result.errors})

        oversized = make_record(matrix, "A5-A")
        oversized["transport_capabilities"]["method_deadlines_s"]["stop"] = 61.0
        result = evaluate_future(matrix, oversized)
        self.assertIn("INVALID_NATIVE_DEADLINE", {i.code for i in result.errors})

    def test_latch_must_be_clear_and_exactly_release_bound(self):
        matrix = make_future_matrix()
        active = make_record(matrix, "A3")
        active["persistent_latch"]["status"] = "ACTIVE"
        result = evaluate_future(matrix, active)
        self.assertIn("PERSISTENT_LATCH_NOT_CLEAR", {i.code for i in result.errors})

        stale = make_record(matrix, "A3")
        stale["persistent_latch"]["profile_manifest_sha256"] = digest("0")
        result = evaluate_future(matrix, stale)
        self.assertIn("LATCH_RELEASE_BINDING_MISMATCH", {i.code for i in result.errors})

    def test_clear_requires_post_latch_generation_after_scope_resign(self):
        matrix = make_future_matrix()
        for generation in (0, 1, 2):
            with self.subTest(generation=generation):
                record = make_record(matrix, "A5-A")
                record["persistent_latch"]["generation"] = generation
                resign_authorization_scope(matrix, record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(
                    "INTEGER_OUT_OF_RANGE",
                    {i.code for i in result.errors},
                )

    def test_clear_rejects_zero_latched_epoch_after_scope_resign(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        record["persistent_latch"]["latched_session_epoch"] = 0
        resign_authorization_scope(matrix, record)
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed)
        self.assertIn("INTEGER_OUT_OF_RANGE", {i.code for i in result.errors})

    def test_clear_requires_a_strictly_newer_session_epoch(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        record["persistent_latch"]["clearing_session_epoch"] = (
            record["persistent_latch"]["latched_session_epoch"])
        resign_authorization_scope(matrix, record)
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed)
        self.assertIn(
            "LATCH_SESSION_EPOCH_NOT_MONOTONIC",
            {i.code for i in result.errors},
        )

    def test_clearance_id_must_match_authorization_after_scope_resign(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-A")
        record["persistent_latch"]["clearance_id"] = "clearance-2"
        resign_authorization_scope(matrix, record)
        result = evaluate_future(matrix, record)
        self.assertFalse(result.allowed)
        self.assertIn("LATCH_CLEARANCE_MISMATCH", {i.code for i in result.errors})

    def test_latch_artifact_drift_is_rejected_after_scope_resign(self):
        matrix = make_future_matrix()
        cases = (
            (
                ("physical_isolation", "evidence_sha256"),
                digest("0"),
                "LATCH_PHYSICAL_ISOLATION_MISMATCH",
            ),
            (
                ("authorization", "authority_evidence_sha256"),
                digest("0"),
                "LATCH_APPROVAL_ARTIFACT_MISMATCH",
            ),
        )
        for path, value, code in cases:
            with self.subTest(path=path):
                record = make_record(matrix, "A5-A")
                set_record_path(record, path, value)
                resign_authorization_scope(matrix, record)
                result = evaluate_future(matrix, record)
                self.assertFalse(result.allowed)
                self.assertIn(code, {i.code for i in result.errors})

    def test_a3_and_a4_both_require_persistent_latch(self):
        matrix = make_future_matrix()
        self.assertTrue(EXPECTED_STAGE_DEFINITIONS["A3"]["requires_persistent_latch"])
        self.assertTrue(EXPECTED_STAGE_DEFINITIONS["A4"]["requires_persistent_latch"])
        for stage_id in ("A3", "A4"):
            with self.subTest(stage=stage_id):
                record = make_record(matrix, stage_id)
                record["persistent_latch"] = None
                result = evaluate_future(matrix, record)
                self.assertIn("PERSISTENT_LATCH_REQUIRED", {i.code for i in result.errors})

    def test_authorization_consumer_receives_full_frozen_scope(self):
        matrix = make_future_matrix()
        record = make_record(matrix, "A5-G")
        observed = {}

        def consume(authorization, scope_sha, consumed_record, policy_sha, now):
            observed.update({
                "authorization_id": authorization["authorization_id"],
                "scope_sha": scope_sha,
                "record": consumed_record,
                "policy_sha": policy_sha,
                "now": now,
            })
            return True

        result = evaluate_future(
            matrix, record, authorization_consumer=consume)
        self.assertTrue(result.allowed, result.as_dict())
        self.assertEqual(record["authorization"]["scope_sha256"], observed["scope_sha"])
        self.assertEqual(canonical_matrix_sha256(matrix), observed["policy_sha"])
        self.assertEqual("A5-G", observed["record"]["stage_id"])


if __name__ == "__main__":
    unittest.main()
