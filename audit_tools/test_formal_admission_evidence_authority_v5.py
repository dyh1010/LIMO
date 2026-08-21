"""Fail-closed tests for the versioned v6 BLOCKED_OFFLINE authority."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit_tools import formal_admission_evidence_authority_v5 as WRAPPER
from audit_tools import formal_admission_evidence_authority_v5_core as CORE
from audit_tools import formal_admission_evidence_authority_v4 as OLD_WRAPPER
from audit_tools import generate_ros1_camera_runtime_root_closure_blocked_offline_evidence_v2 as GENERATOR


ROOT = Path(__file__).resolve().parents[1]


def _json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write(root, relative, raw):
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "root_role": "workspace",
        "path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _write_json(root, relative, value):
    return _write(root, relative, _json_bytes(value))


def _stream(raw=b""):
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha(value):
    return hashlib.sha256(CORE._canonical_json(value)).hexdigest()


class FormalAdmissionEvidenceAuthorityV5Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.doc_target = "audit_tools/test_ros1_machine_contract_doc_demotion.py"
        self.runner_target = CORE.UNITTEST_RUNNER
        self.test_id = CORE.DOC_DEMOTION_LINK_CASE_ID
        _write(
            self.root, self.doc_target,
            (
                "import unittest\n\n"
                "class Ros1MachineContractDocDemotionTest(unittest.TestCase):\n"
                "    def test_document_symlink_is_rejected(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        _write(self.root, self.runner_target, b"# isolated runner fixture\n")
        for relative in (
            "audit_tools/ros1_camera_runtime_import_probe.py",
            "audit_tools/ros1_camera_runtime_install_admission.py",
            "audit_tools/ros1_camera_only_atomic_launcher.py",
        ):
            _write(self.root, relative, ("# " + relative + "\n").encode("utf-8"))
        _write(self.root, "overlay/a.py", b"VALUE = 1\n")

        self.predecessor_evidence_id = "fixture_predecessor_evidence"
        self.predecessor_generation_id = "fixture_predecessor_generation"
        predecessor_report = {
            "evidence_id": self.predecessor_evidence_id,
            "generation_id": self.predecessor_generation_id,
            "regression_passed": False,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
        }
        predecessor_canonical = {
            "generation_id": self.predecessor_generation_id,
            "delivery_ready": False,
            "authorizes_field_delivery": False,
        }
        predecessor_index = {
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": "fixture-predecessor-index",
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
            "accepted_by_formal_field_evidence_consumer": False,
            "authorizes_field_delivery": False,
            "entries": [{
                "evidence_id": self.predecessor_evidence_id,
                "is_current": True,
            }],
        }
        self.predecessor_report_identity = _write_json(
            self.root, "frozen/predecessor_report.json", predecessor_report,
        )
        self.predecessor_canonical_identity = _write_json(
            self.root, "frozen/predecessor_canonical.json", predecessor_canonical,
        )
        self.predecessor_index_identity = _write_json(
            self.root, "frozen/predecessor_index.json", predecessor_index,
        )
        self.predecessor_index_identity.update({
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": "fixture-predecessor-index",
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
        })

        source_definitions = (
            ("doc_test", "workspace", self.doc_target),
            ("unittest_runner", "workspace", self.runner_target),
            ("probe", "workspace", "audit_tools/ros1_camera_runtime_import_probe.py"),
            ("install", "workspace", "audit_tools/ros1_camera_runtime_install_admission.py"),
            ("atomic", "workspace", "audit_tools/ros1_camera_only_atomic_launcher.py"),
            ("predecessor_index", "workspace", "frozen/predecessor_index.json"),
            ("predecessor_report", "workspace", "frozen/predecessor_report.json"),
            ("predecessor_canonical", "workspace", "frozen/predecessor_canonical.json"),
        )
        suites = ({
            "suite_id": "machine_contract_doc_demotion",
            "root_role": "workspace",
            "target": self.doc_target,
            "runner": "unittest",
        },)
        executions = (
            {
                "record_id": "doc_demotion_windows_bundled",
                "suite_id": "machine_contract_doc_demotion",
                "platform": "WINDOWS_HOST",
                "interpreter_role": "bundled_host_python",
                "selection": "ALL",
            },
            {
                "record_id": "doc_demotion_link_posix_companion",
                "suite_id": "machine_contract_doc_demotion",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": self.test_id,
            },
        )
        self.policy = CORE.AuthorityPolicy(
            index_relative_path="out/index.json",
            report_relative_path="out/report.json",
            canonical_relative_path="out/canonical.json",
            source_role_definitions=source_definitions,
            suite_definitions=suites,
            execution_definitions=executions,
            predecessor_index_identity=self.predecessor_index_identity,
            predecessor_report_identity=self.predecessor_report_identity,
            predecessor_canonical_identity=self.predecessor_canonical_identity,
            frozen_source_identities={},
            live_overlay_root="overlay",
            required_live_overlay_paths=("a.py",),
            host_perception_package_root=None,
            host_perception_package_files=(),
            host_perception_cache_files=(),
            allowed_empty_source_paths=(),
        )
        self.source_roles = CORE.collect_source_role_bindings(
            self.root, self.policy,
        )
        self.logical = CORE.expected_logical_suite_records(
            self.root, self.source_roles, self.policy,
        )
        self.physical = sorted([
            self._physical_record(
                "doc_demotion_windows_bundled", "WINDOWS_HOST",
                "bundled_host_python", passed=False,
            ),
            self._physical_record(
                "doc_demotion_link_posix_companion", "POSIX_WSL",
                "system_python314_target", passed=True,
            ),
        ], key=lambda item: item["record_id"])
        failures, by_id = CORE._validate_physical_records(
            self.root, self.physical, self.source_roles, self.policy,
        )
        self.assertEqual(failures, [])
        self.composites = CORE._expected_platform_composites(by_id)
        self.observations = self._production_observations()

        canonical = CORE.build_canonical_payload(
            self.root, self.source_roles, self.policy,
        )
        self.canonical_identity = CORE.write_json_exclusive(
            self.root / "out" / "canonical.json", canonical,
            self.policy.canonical_relative_path,
        )
        self.report = CORE.build_report_payload(
            self.root, self.canonical_identity, self.source_roles,
            self.logical, self.physical, self.composites, self.observations,
            self.policy,
        )
        self.report_identity = CORE.write_json_exclusive(
            self.root / "out" / "report.json", self.report,
            self.policy.report_relative_path,
        )
        self.payload = CORE.build_index_payload(
            self.report_identity, self.canonical_identity,
            self.source_roles, self.policy,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _source(self, relative):
        item = next(
            record for record in self.source_roles
            if record["root_role"] == "workspace" and record["path"] == relative
        )
        return {
            key: item[key]
            for key in ("root_role", "path", "size_bytes", "sha256")
        }

    def _interpreter_identity(self, role):
        if role == "bundled_host_python":
            entry_path = str(self.root / "bundled-python.exe")
            entry_is_symlink = False
            entry_link_chain = []
            target_path = entry_path
        elif role == "system_python3_entry":
            entry_path = "/usr/bin/python3"
            entry_is_symlink = True
            entry_link_chain = [{
                "path": "/usr/bin/python3",
                "target": "python3.14",
            }]
            target_path = "/usr/bin/python3.14"
        elif role == "system_python314_target":
            entry_path = "/usr/bin/python3.14"
            entry_is_symlink = False
            entry_link_chain = []
            target_path = entry_path
        else:
            raise AssertionError("unexpected interpreter role: " + role)
        return {
            "entry_path": entry_path,
            "entry_is_symlink": entry_is_symlink,
            "entry_lstat_size_bytes": 32,
            "entry_link_chain": entry_link_chain,
            "resolved_target": {
                "path": target_path,
                "size_bytes": 4096,
                "sha256": "1" * 64,
                "regular_file": True,
                "is_symlink": False,
            },
            "isolated": True,
            "no_bytecode": True,
            "version": [3, 14, 0],
        }

    @staticmethod
    def _orchestrator_identity():
        return {
            "path": r"C:\Windows\System32\wsl.exe",
            "size_bytes": 4096,
            "sha256": "2" * 64,
            "hardlink_count": 2,
        }

    def _physical_record(self, record_id, platform, interpreter_role, passed):
        test_identity = self._source(self.doc_target)
        runner_identity = self._source(self.runner_target)
        passed_ids = [self.test_id] if passed else []
        skipped_ids = [] if passed else [self.test_id]
        marker = {
            "path": self.doc_target,
            "size_bytes": test_identity["size_bytes"],
            "sha256": test_identity["sha256"],
            "expected_ids": [self.test_id],
            "executed_ids": [self.test_id],
            "collected": 1,
            "passed": len(passed_ids),
            "failed": 0,
            "skipped": len(skipped_ids),
        }
        interpreter_identity = self._interpreter_identity(interpreter_role)
        orchestrator_identity = (
            None if platform == "WINDOWS_HOST"
            else self._orchestrator_identity()
        )
        definition = next(
            item for item in self.policy.execution_definitions
            if item["record_id"] == record_id
        )
        suite = next(
            item for item in CORE.suite_inventory(self.root, self.policy)
            if item["suite_id"] == definition["suite_id"]
        )
        argv = CORE._expected_child_argv(
            self.root, definition, suite, [self.test_id],
            interpreter_identity, orchestrator_identity,
        )
        environment = (
            {"SystemRoot": r"C:\Windows"}
            if platform == "WINDOWS_HOST"
            else dict(CORE.CHILD_ENVIRONMENT)
        )
        marker["executable"] = interpreter_identity
        return {
            "record_id": record_id,
            "suite_id": "machine_contract_doc_demotion",
            "platform": platform,
            "interpreter_role": interpreter_role,
            "test_artifact_identity": test_identity,
            "runner_artifact_identity": runner_identity,
            "interpreter_identity": interpreter_identity,
            "orchestrator_identity": orchestrator_identity,
            "expected_test_ids": [self.test_id],
            "executed_test_ids": [self.test_id],
            "passed_ids": passed_ids,
            "failed_ids": [],
            "skipped_ids": skipped_ids,
            "collected": 1,
            "passed": len(passed_ids),
            "failed": 0,
            "skipped": len(skipped_ids),
            "exit_code": 0,
            "marker_count": 1,
            "marker_prefix": CORE.UNITTEST_MARKER,
            "marker_payload": marker,
            "marker_payload_sha256": _sha(marker),
            "argv": argv,
            "argv_sha256": _sha(argv),
            "environment": environment,
            "environment_sha256": _sha(environment),
            "stdout": _stream(),
            "stderr": _stream(),
        }

    def _production_observations(self):
        result = []
        for definition in CORE.PRODUCTION_CLI_EXPECTATIONS:
            source = self._source(definition["source_path"])
            attempted = definition["execution_attempted"]
            if attempted:
                interpreter_identity = self._interpreter_identity(
                    "system_python314_target"
                )
                orchestrator_identity = self._orchestrator_identity()
                wsl_root = CORE._execution_workspace_path(self.root)
                environment = dict(CORE.CHILD_ENVIRONMENT)
                argv = [
                    orchestrator_identity["path"], "--cd", wsl_root,
                    "--exec", "/usr/bin/env", "-i",
                    *[
                        key + "=" + value
                        for key, value in sorted(environment.items())
                    ],
                    "/usr/bin/python3.14", "-I", "-S", "-B",
                    str(Path(wsl_root, definition["source_path"]))
                    if not wsl_root.startswith("/")
                    else wsl_root.rstrip("/") + "/" + definition["source_path"],
                ]
            else:
                interpreter_identity = None
                orchestrator_identity = None
                argv = ["NOT_EXECUTED_SAFETY_BOUNDARY"]
                environment = {}
            payload = (
                {
                    "failures": [definition["blocked_code"]],
                    "validated_pass": False,
                    "delivery_ready": False,
                }
                if attempted else {
                    "execution_attempted": False,
                    "supporting_test_id": definition["supporting_test_id"],
                    "supporting_record_ids": [
                        "atomic_wsl_python3", "atomic_wsl_python314",
                    ],
                    "blocked_code": definition["blocked_code"],
                }
            )
            result.append({
                "observation_id": definition["observation_id"],
                "source_identity_before": source,
                "source_identity_after": source,
                "interpreter_identity": interpreter_identity,
                "orchestrator_identity": orchestrator_identity,
                "argv": argv,
                "argv_sha256": _sha(argv),
                "environment": environment,
                "environment_sha256": _sha(environment),
                "exit_code": definition["exit_code"],
                "marker_count": definition["marker_count"],
                "blocked_code": definition["blocked_code"],
                "failure_codes": [definition["blocked_code"]],
                "stdout": _stream(),
                "stderr": _stream(),
                "payload": payload,
                "payload_sha256": _sha(payload),
                "expected_fail_closed": True,
                "not_in_logical_denominator": True,
                "not_in_physical_denominator": True,
                "formal_consumer": False,
                "delivery_ready": False,
                "self_reported_anchor_accepted": False,
                "execution_attempted": attempted,
                "supporting_test_id": definition["supporting_test_id"],
            })
        return sorted(result, key=lambda item: item["observation_id"])

    def _validate(self, payload=None):
        return CORE.validate_formal_admission_evidence_authority_v5(
            self.root, self.payload if payload is None else payload,
            self.policy,
        )

    def _replace_report(self, mutate):
        value = deepcopy(self.report)
        mutate(value)
        material = dict(value)
        material.pop("report_binding_sha256", None)
        value["report_binding_sha256"] = _sha(material)
        path = self.root / self.policy.report_relative_path
        path.write_bytes(_json_bytes(value))
        identity = {
            "path": self.policy.report_relative_path,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self.payload = CORE.build_index_payload(
            identity, self.canonical_identity, self.source_roles, self.policy,
        )

    def test_valid_payload_is_offline_only(self):
        result = self._validate()
        self.assertTrue(result["semantic_validated_pass"], result["failures"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["ros1_noetic_runtime_verified"])
        self.assertFalse(result["ros1_noetic_build_install_verified"])
        self.assertFalse(result["delivery_ready"])

    def test_exact_anchor_resolver_accepts_only_offline_selection(self):
        identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        result = CORE.load_and_resolve_formal_admission_evidence_authority_v5(
            self.root, identity, self.policy,
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["delivery_ready"])
        self.assertEqual(result["current_evidence"]["evidence_id"], CORE.CURRENT_EVIDENCE_ID)

    def test_wrong_anchor_path_size_and_hash_fail_closed(self):
        identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        for key, value in (
            ("path", "out/other.json"),
            ("size_bytes", identity["size_bytes"] + 1),
            ("sha256", "0" * 64),
        ):
            anchor = dict(identity)
            anchor[key] = value
            result = CORE.load_and_resolve_formal_admission_evidence_authority_v5(
                self.root, anchor, self.policy,
            )
            self.assertFalse(result["validated_pass"], key)
            self.assertIsNone(result["current_evidence"], key)

    def test_missing_and_duplicate_current_are_rejected(self):
        for mutate in (
            lambda value: value["entries"][1].update(is_current=False),
            lambda value: value["entries"][0].update(is_current=True),
        ):
            payload = deepcopy(self.payload)
            mutate(payload)
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"])
            self.assertIn("formal_authority_v5_current_count_invalid", result["failures"])

    def test_old_v5_entry_cannot_be_repromoted(self):
        payload = deepcopy(self.payload)
        payload["entries"][0]["is_current"] = True
        payload["entries"][1]["is_current"] = False
        payload["current_evidence_id"] = self.predecessor_evidence_id
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("current" in item for item in result["failures"]))

    def test_predecessor_identity_and_instance_are_exact(self):
        for key, value in (
            ("index_instance_id", "wrong"),
            ("size_bytes", self.predecessor_index_identity["size_bytes"] + 1),
            ("sha256", "0" * 64),
        ):
            payload = deepcopy(self.payload)
            payload["predecessor_authority_index"][key] = value
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

    def test_source_role_root_path_size_and_hash_are_exact(self):
        for key, value in (
            ("root_role", "workspace_parent"),
            ("path", "audit_tools/other.py"),
            ("size_bytes", 999),
            ("sha256", "0" * 64),
        ):
            payload = deepcopy(self.payload)
            payload["source_roles"][0][key] = value
            payload["source_role_set_sha256"] = _sha(payload["source_roles"])
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

    def test_missing_duplicate_source_roles_and_missing_canonical_child_are_rejected(self):
        payload = deepcopy(self.payload)
        payload["source_roles"].pop()
        payload["source_role_count"] = len(payload["source_roles"])
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn("formal_authority_v5_source_role_set_invalid", result["failures"])

        payload = deepcopy(self.payload)
        payload["source_roles"].append(deepcopy(payload["source_roles"][0]))
        payload["source_role_count"] = len(payload["source_roles"])
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "source_role_duplicate" in failure
            for failure in result["failures"]
        ))

        payload = deepcopy(self.payload)
        payload["child_artifacts"] = []
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v5_child_artifacts_invalid", result["failures"]
        )

    def test_unhashable_json_identity_fields_fail_closed_without_exception(self):
        payload = deepcopy(self.payload)
        payload["source_roles"][0]["path"] = []
        payload["source_role_set_sha256"] = _sha(payload["source_roles"])
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "source_role_identity_type_invalid" in failure
            for failure in result["failures"]
        ))

        payload = deepcopy(self.payload)
        payload["entries"][1]["evidence_id"] = []
        result = self._validate(payload)
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn("formal_authority_v5_entry_invalid", result["failures"])

        self._replace_report(
            lambda value: value["test_matrix"][
                "physical_execution_records"
            ][0].update(record_id=[])
        )
        result = self._validate()
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "physical_record_id_invalid" in failure
            for failure in result["failures"]
        ))

        self._replace_report(
            lambda value: value["production_cli_observations"][0].update(
                observation_id=[]
            )
        )
        result = self._validate()
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "production_observation_id_invalid" in failure
            for failure in result["failures"]
        ))

    def test_source_artifact_drift_is_rejected(self):
        path = self.root / "audit_tools" / "ros1_camera_runtime_import_probe.py"
        path.write_bytes(path.read_bytes() + b"# drift\n")
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("source_role_identity_mismatch" in item for item in result["failures"]))

    def test_nonformal_diagnostic_source_is_forbidden(self):
        definitions = self.policy.source_role_definitions + (
            ("bad", "workspace", "evidence/NON_FORMAL_UNSELECTED_diagnostic.json"),
        )
        bad_policy = CORE.AuthorityPolicy(
            **{
                **self.policy.__dict__,
                "source_role_definitions": definitions,
            }
        )
        result = CORE.validate_formal_admission_evidence_authority_v5(
            self.root, self.payload, bad_policy,
        )
        self.assertIn(
            "formal_authority_v5_policy_nonformal_diagnostic_forbidden",
            result["failures"],
        )

    def test_logical_denominator_is_recomputed_from_ast(self):
        self.assertEqual(len(self.logical), 1)
        self.assertEqual(self.logical[0]["collected"], 1)
        self._replace_report(
            lambda value: value["test_matrix"].update(
                logical_expected_total=187,
            )
        )
        result = self._validate()
        self.assertIn(
            "formal_authority_v5_report_test_count_mismatch:logical_expected_total",
            result["failures"],
        )

    def test_physical_denominator_and_zero_denominator_forgery_are_rejected(self):
        self._replace_report(
            lambda value: value["test_matrix"].update(
                physical_expected_total=0,
                physical_collected=0,
                physical_effective_passed=0,
            )
        )
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("physical_" in item for item in result["failures"]))

    def test_windows_skip_requires_same_id_posix_pass(self):
        def mutate(value):
            companion = next(
                item for item in value["test_matrix"]["physical_execution_records"]
                if item["record_id"] == "doc_demotion_link_posix_companion"
            )
            companion["passed_ids"] = []
            companion["skipped_ids"] = [self.test_id]
            companion["passed"] = 0
            companion["skipped"] = 1
            companion["marker_payload"]["passed"] = 0
            companion["marker_payload"]["skipped"] = 1
            companion["marker_payload_sha256"] = _sha(companion["marker_payload"])
        self._replace_report(mutate)
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any(
            "unapproved_physical_skip" in item or "platform_composite" in item
            for item in result["failures"]
        ))

    def test_duplicate_or_missing_marker_is_rejected(self):
        for count in (0, 2):
            def mutate(value, count=count):
                value["test_matrix"]["physical_execution_records"][0]["marker_count"] = count
            self._replace_report(mutate)
            result = self._validate()
            self.assertFalse(result["semantic_validated_pass"], count)
            self.tearDown()
            self.setUp()

    def test_production_observation_self_report_and_atomic_execution_are_rejected(self):
        for key, value in (
            ("self_reported_anchor_accepted", True),
            ("execution_attempted", True),
        ):
            def mutate(report, key=key, value=value):
                item = next(
                    record for record in report["production_cli_observations"]
                    if record["observation_id"] == "atomic_runtime_admission_unbound"
                )
                item[key] = value
            self._replace_report(mutate)
            result = self._validate()
            self.assertFalse(result["semantic_validated_pass"], key)
            self.tearDown()
            self.setUp()

    def test_wrong_production_blocked_code_is_rejected(self):
        def mutate(report):
            item = report["production_cli_observations"][0]
            item["blocked_code"] = "forged_pass"
            item["failure_codes"] = ["forged_pass"]
        self._replace_report(mutate)
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("production_observation_mismatch" in item for item in result["failures"]))

    def test_runtime_field_delivery_and_regression_promotions_are_rejected(self):
        for container, key in (
            ("top", "accepted_by_formal_field_evidence_consumer"),
            ("top", "authorizes_field_delivery"),
            ("gate", "ros1_noetic_runtime_verified"),
            ("gate", "ros1_noetic_build_install_verified"),
            ("gate", "ros1_noetic_field_install_pass"),
            ("gate", "formal_acceptance"),
            ("gate", "formal_tf_pass"),
            ("gate", "formal_3d_pass"),
            ("gate", "formal_latency_pass"),
            ("gate", "delivery_ready"),
            ("gate", "regression_passed"),
        ):
            payload = deepcopy(self.payload)
            target = payload if container == "top" else payload["gate_state"]
            target[key] = True
            result = self._validate(payload)
            self.assertFalse(result["semantic_validated_pass"], key)

        payload = deepcopy(self.payload)
        payload["gate_state"]["formal_denominator"] = 1
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])

    def test_canonical_report_and_index_share_exact_blocked_gate_state(self):
        canonical = CORE.build_canonical_payload(
            self.root, self.source_roles, self.policy,
        )
        self.assertEqual(canonical["gate_state"], dict(CORE.GATE_STATE))
        self.assertEqual(self.report["gate_state"], dict(CORE.GATE_STATE))
        self.assertEqual(self.payload["gate_state"], dict(CORE.GATE_STATE))
        for gate in (canonical["gate_state"], self.report["gate_state"], self.payload["gate_state"]):
            self.assertFalse(gate["formal_acceptance"])
            self.assertEqual(gate["formal_denominator"], 0)
            self.assertFalse(gate["ros1_noetic_runtime_verified"])
            self.assertFalse(gate["ros1_noetic_build_install_verified"])
            self.assertFalse(gate["formal_tf_pass"])
            self.assertFalse(gate["formal_3d_pass"])
            self.assertFalse(gate["formal_latency_pass"])
            self.assertFalse(gate["delivery_ready"])

    def test_filename_or_mtime_selection_is_rejected(self):
        payload = deepcopy(self.payload)
        payload["uses_filename_or_mtime_authority"] = True
        payload["filename_mtime_selection_forbidden"] = False
        result = self._validate(payload)
        self.assertFalse(result["semantic_validated_pass"])

    def test_generation_inventory_rejects_id_collision_not_filename_or_mtime(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        collision = evidence / "unrelated-name.json"
        collision.write_bytes(_json_bytes({
            "generation_id": CORE.GENERATION_ID,
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [{
            "path": "evidence/unrelated-name.json",
            "field": "generation_id",
            "value": CORE.GENERATION_ID,
        }])

        collision.unlink()
        noncollision = evidence / (CORE.GENERATION_ID + ".json")
        noncollision.write_bytes(_json_bytes({
            "generation_id": "historical-unrelated-generation",
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [])

    def test_strict_json_rejects_duplicate_nan_and_trailing_content(self):
        for raw in (
            b'{"schema_version":1,"schema_version":2}',
            b'{"value":NaN}',
            b'{} trailing',
        ):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                CORE._strict_json_bytes(raw)

    def test_exclusive_writer_refuses_overwrite(self):
        path = self.root / "out" / "exclusive.json"
        CORE.write_json_exclusive(path, {"value": 1}, "out/exclusive.json")
        with self.assertRaises(FileExistsError):
            CORE.write_json_exclusive(path, {"value": 2}, "out/exclusive.json")

    def test_workspace_parent_is_an_explicit_independent_root(self):
        parent_file = self.root.parent / (self.root.name + "_shared.md")
        try:
            parent_file.write_bytes(b"shared\n")
            identity = CORE.source_artifact_identity(
                self.root, "workspace_parent", parent_file.name,
            )
            self.assertEqual(identity["root_role"], "workspace_parent")
            with self.assertRaises(ValueError):
                CORE.source_artifact_identity(
                    self.root, "workspace", "../" + parent_file.name,
                )
        finally:
            parent_file.unlink(missing_ok=True)

    def test_production_policy_uses_root_roles_and_excludes_diagnostics(self):
        definitions = CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS
        self.assertTrue(any(item[1] == "workspace_parent" for item in definitions))
        self.assertFalse(any(
            item[2].lower().startswith("evidence/")
            and "diagnostic" in item[2].lower()
            for item in definitions
        ))
        required_transitive_roles = (
            ("legacy_operational_scripts_test", "workspace", "audit_tools/test_ros1_legacy_operational_scripts.py"),
            ("runtime_behavior_nested_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_runtime_behavior.py"),
            ("dabai_field_readiness_runbook", "workspace", "docs/PERCEPTION_V2_FIELD_READINESS_RUNBOOK.md"),
            ("dabai_sensor_package_readme", "workspace", "src/limo_cleanup_dabai_sensor/README.md"),
            ("perception_release_preflight", "workspace", "scripts/perception_release_preflight.py"),
            ("perception_release_rollback", "workspace", "scripts/rollback_perception_release.sh"),
            ("preflight_predecessor_authority_v4", "workspace", "evidence/perception_v2_offline_20260813/ros1_formal_admission_evidence_authority_index_20260815_v4.json"),
            ("preflight_frozen_canonical_v5", "workspace", "evidence/perception_v2_offline_20260813/ros1_noetic_canonical_source_admission_20260815_v5.json"),
            ("preflight_frozen_report_v4", "workspace", "evidence/perception_v2_offline_20260813/frozen_offline_regression_20260815_runner_platform_composite_v4.json"),
        )
        for expected in required_transitive_roles:
            self.assertIn(expected, definitions)
        host_paths = {
            path for unused_role, root_role, path in definitions
            if (
                root_role == "workspace"
                and path.startswith(CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/")
                and "/__pycache__/" not in path
            )
        }
        self.assertEqual(host_paths, {
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/" + name
            for name in CORE.HOST_PERCEPTION_PACKAGE_FILES
        })
        host_cache_paths = {
            path for unused_role, root_role, path in definitions
            if (
                root_role == "workspace"
                and path.startswith(
                    CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/"
                )
            )
        }
        self.assertEqual(host_cache_paths, {
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/" + name
            for name in CORE.HOST_PERCEPTION_CACHE_FILES
        })

    def test_host_perception_package_exact_tree_rejects_extra_missing_and_drift(self):
        package_root = "fixture_host_perception_package"
        files = ("a.py", "b.py")
        cache_files = ("a.cpython-314.pyc",)
        definitions = self.policy.source_role_definitions + tuple(
            (
                "fixture_host_package_" + name.replace(".", "_"),
                "workspace", package_root + "/" + name,
            )
            for name in files
        ) + tuple(
            (
                "fixture_host_cache_" + name.replace(".", "_"),
                "workspace", package_root + "/__pycache__/" + name,
            )
            for name in cache_files
        )
        for name in files:
            _write(
                self.root, package_root + "/" + name,
                (name + "\n").encode("utf-8"),
            )
        _write(
            self.root, package_root + "/__pycache__/" + cache_files[0],
            b"fixture pyc bytes\n",
        )
        policy = CORE.AuthorityPolicy(**{
            **self.policy.__dict__,
            "source_role_definitions": definitions,
            "host_perception_package_root": package_root,
            "host_perception_package_files": files,
            "host_perception_cache_files": cache_files,
        })
        roles = CORE.collect_source_role_bindings(self.root, policy)
        binding = CORE.collect_host_perception_package_tree(
            self.root, policy,
        )
        self.assertEqual(binding["file_count"], 3)
        planned_binding, plan_error = GENERATOR._host_tree_plan_state(
            CORE, self.root, policy,
        )
        self.assertEqual(plan_error, None)
        self.assertEqual(planned_binding, binding)

        original_scandir = CORE.os.scandir
        between_scan_extra = self.root / package_root / "between_scan.py"
        calls = {"count": 0}
        def add_source_between_scans(path):
            calls["count"] += 1
            if calls["count"] == 3:
                between_scan_extra.write_bytes(b"between scans\n")
            return original_scandir(path)
        CORE.os.scandir = add_source_between_scans
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.os.scandir = original_scandir
            between_scan_extra.unlink(missing_ok=True)

        between_cache_extra = (
            self.root / package_root / "__pycache__" /
            "between_scan.cpython-314.pyc"
        )
        calls = {"count": 0}
        def add_cache_between_scans(path):
            calls["count"] += 1
            if calls["count"] == 4:
                between_cache_extra.write_bytes(b"between cache scans\n")
            return original_scandir(path)
        CORE.os.scandir = add_cache_between_scans
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.os.scandir = original_scandir
            between_cache_extra.unlink(missing_ok=True)

        original_identity = CORE.source_artifact_identity
        source_path = self.root / package_root / "a.py"
        calls = {"count": 0}
        def mutate_source_before_final_read(workspace, root_role, relative):
            calls["count"] += 1
            if calls["count"] == 4:
                source_path.write_bytes(b"in-place source drift\n")
            return original_identity(workspace, root_role, relative)
        CORE.source_artifact_identity = mutate_source_before_final_read
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.source_artifact_identity = original_identity
            source_path.write_bytes(b"a.py\n")

        cache_path = (
            self.root / package_root / "__pycache__" / cache_files[0]
        )
        calls = {"count": 0}
        def mutate_cache_before_final_read(workspace, root_role, relative):
            calls["count"] += 1
            if calls["count"] == 6:
                cache_path.write_bytes(b"in-place cache drift\n")
            return original_identity(workspace, root_role, relative)
        CORE.source_artifact_identity = mutate_cache_before_final_read
        try:
            with self.assertRaises(ValueError):
                CORE.collect_host_perception_package_tree(self.root, policy)
        finally:
            CORE.source_artifact_identity = original_identity
            cache_path.write_bytes(b"fixture pyc bytes\n")

        extra = self.root / package_root / "extra.py"
        extra.write_bytes(b"EXTRA = True\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_host_package_tree_invalid", failures,
        )
        extra.unlink()

        extra_cache = (
            self.root / package_root / "__pycache__" / "extra.cpython-314.pyc"
        )
        extra_cache.write_bytes(b"extra pyc\n")
        planned_binding, plan_error = GENERATOR._host_tree_plan_state(
            CORE, self.root, policy,
        )
        self.assertIsNone(planned_binding)
        self.assertIn("exact file set mismatch", plan_error)
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_host_package_tree_invalid", failures,
        )
        extra_cache.unlink()

        missing_cache = (
            self.root / package_root / "__pycache__" / cache_files[0]
        )
        missing_cache.unlink()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_host_package_tree_invalid", failures,
        )
        missing_cache.write_bytes(b"fixture pyc bytes\n")

        cache_subdirectory = self.root / package_root / "__pycache__" / "nested"
        cache_subdirectory.mkdir()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_host_package_tree_invalid", failures,
        )
        cache_subdirectory.rmdir()

        link = self.root / package_root / "__pycache__" / "linked.pyc"
        try:
            link.symlink_to(missing_cache)
        except OSError:
            link = None
        if link is not None:
            failures, unused = CORE._validate_source_roles(
                self.root, roles, policy,
            )
            self.assertIn(
                "formal_authority_v5_host_package_tree_invalid", failures,
            )
            link.unlink()

        missing = self.root / package_root / "b.py"
        missing.unlink()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_host_package_tree_invalid", failures,
        )
        missing.write_bytes(b"b.py\n")

        roles = CORE.collect_source_role_bindings(self.root, policy)
        (self.root / package_root / "a.py").write_bytes(b"DRIFT = True\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertTrue(any(
            "source_role_identity_mismatch" in failure
            for failure in failures
        ))

        (self.root / package_root / "a.py").write_bytes(b"a.py\n")
        roles = CORE.collect_source_role_bindings(self.root, policy)
        missing_cache.write_bytes(b"drifted pyc\n")
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertTrue(any(
            "source_role_identity_mismatch" in failure
            for failure in failures
        ))

    def test_only_exact_host_package_init_may_be_empty(self):
        init_path = (
            CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__init__.py"
        )
        init_identity = CORE.source_artifact_identity(
            ROOT, "workspace", init_path,
        )
        self.assertEqual(init_identity["size_bytes"], 0)
        self.assertEqual(
            CORE._identity_failures(
                init_identity, "fixture", with_root=True, allow_empty=True,
            ),
            [],
        )
        self.assertIn(
            "fixture_size_invalid",
            CORE._identity_failures(
                init_identity, "fixture", with_root=True, allow_empty=False,
            ),
        )
        self.assertEqual(
            CORE.ALLOWED_EMPTY_SOURCE_PATHS,
            (("workspace", init_path),),
        )
        binding = CORE.collect_host_perception_package_tree(ROOT)
        self.assertEqual(
            binding["file_count"],
            len(CORE.HOST_PERCEPTION_PACKAGE_FILES)
            + len(CORE.HOST_PERCEPTION_CACHE_FILES),
        )
        self.assertEqual(
            {item["path"] for item in binding["entries"]},
            set(CORE.HOST_PERCEPTION_PACKAGE_FILES) | {
                "__pycache__/" + name
                for name in CORE.HOST_PERCEPTION_CACHE_FILES
            },
        )

        empty_path = "empty_unrelated_role.txt"
        _write(self.root, empty_path, b"")
        policy = CORE.AuthorityPolicy(**{
            **self.policy.__dict__,
            "source_role_definitions": self.policy.source_role_definitions + (
                ("empty_unrelated_role", "workspace", empty_path),
            ),
        })
        roles = CORE.collect_source_role_bindings(self.root, policy)
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v5_source_role_size_invalid", failures,
        )

    def test_production_suite_inventory_is_mechanical_and_contains_new_suites(self):
        inventory = CORE.suite_inventory(ROOT)
        by_id = {item["suite_id"]: item for item in inventory}
        for suite_id in (
            "camera_runtime_import_probe", "camera_runtime_install_admission",
            "camera_only_atomic_launcher", "machine_contract_doc_demotion",
            "camera_only_operator_docs", "runtime_source_contract",
            "dabai_runtime_contract", "legacy_operational_scripts",
            "perception_release_artifacts", "successor_authority_validator",
        ):
            self.assertIn(suite_id, by_id)
            self.assertGreater(by_id[suite_id]["logical_count"], 0)
        self.assertIn(
            CORE.ATOMIC_SUPPORTING_TEST_ID,
            by_id["camera_only_atomic_launcher"]["expected_test_ids"],
        )

    def test_legacy_suite_has_two_physical_interpreters_but_one_logical_suite(self):
        records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "legacy_operational_scripts"
        ]
        self.assertEqual(
            {item["interpreter_role"] for item in records},
            {"system_python3_entry", "system_python314_target"},
        )
        self.assertEqual(
            sum(item["suite_id"] == "legacy_operational_scripts" for item in CORE.SUITE_DEFINITIONS),
            1,
        )

    def test_runtime_source_uses_bundled_host_python_with_real_numpy_behavior_child(self):
        records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "runtime_source_contract"
        ]
        self.assertEqual(records, [{
            "record_id": "runtime_source_windows_bundled",
            "suite_id": "runtime_source_contract",
            "platform": "WINDOWS_HOST",
            "interpreter_role": "bundled_host_python",
            "selection": "ALL",
        }])

    def test_wrapper_production_anchor_is_self_consistent_before_and_after_freeze(self):
        configured_anchor = WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR
        try:
            WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR = None
            result = WRAPPER.load_and_resolve_current_authority(ROOT)
            self.assertFalse(result["validated_pass"])
            self.assertFalse(result["production_anchor_configured"])
            self.assertIn(
                "formal_authority_v5_production_anchor_not_configured",
                result["failures"],
            )
        finally:
            WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR = configured_anchor

        if configured_anchor is None:
            return
        self.assertEqual(
            set(configured_anchor), {"path", "size_bytes", "sha256"},
        )
        self.assertEqual(configured_anchor["path"], CORE.INDEX_RELATIVE_PATH)
        index_path = ROOT.joinpath(*configured_anchor["path"].split("/"))
        raw = index_path.read_bytes()
        self.assertEqual(configured_anchor["size_bytes"], len(raw))
        self.assertEqual(
            configured_anchor["sha256"], hashlib.sha256(raw).hexdigest(),
        )
        result = WRAPPER.load_and_resolve_current_authority(ROOT)
        self.assertTrue(result["validated_pass"])
        self.assertTrue(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertIsNotNone(result["current_evidence"])

    def test_wrapper_configured_anchor_uses_exact_core_resolver_offline_only(self):
        index_identity = CORE.write_json_exclusive(
            self.root / self.policy.index_relative_path, self.payload,
            self.policy.index_relative_path,
        )
        original_loader = WRAPPER._load_exact_core
        original_anchor = WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR
        original_policy = CORE.PRODUCTION_POLICY
        try:
            CORE.PRODUCTION_POLICY = self.policy
            WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR = dict(index_identity)
            WRAPPER._load_exact_core = lambda workspace: (
                CORE,
                {
                    "path": WRAPPER.CORE_SOURCE_RELATIVE_PATH,
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
                [],
            )
            result = WRAPPER.load_and_resolve_current_authority(self.root)
        finally:
            WRAPPER._load_exact_core = original_loader
            WRAPPER.PRODUCTION_INDEX_TRUST_ANCHOR = original_anchor
            CORE.PRODUCTION_POLICY = original_policy
        self.assertTrue(result["production_anchor_configured"])
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertIsNotNone(result["current_evidence"])

    def test_wrapper_core_source_anchor_matches_live_core_before_generation(self):
        core_path = ROOT / WRAPPER.CORE_SOURCE_RELATIVE_PATH
        raw = core_path.read_bytes()
        expected = {
            "path": WRAPPER.CORE_SOURCE_RELATIVE_PATH,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        self.assertEqual(WRAPPER.CORE_SOURCE_TRUST_ANCHOR, expected)
        status = GENERATOR._wrapper_core_anchor_status(ROOT, expected)
        self.assertTrue(status["matches_live_core"])
        self.assertEqual(status["configured_core_anchor"], expected)
        core, identity, failures = WRAPPER._load_exact_core(ROOT)
        self.assertEqual(failures, [])
        self.assertIsNotNone(core)
        self.assertEqual(identity, expected)

    def test_old_resolver_cannot_select_the_new_generation_path(self):
        result = OLD_WRAPPER.load_and_resolve_successor_authority({
            "path": CORE.INDEX_RELATIVE_PATH,
            "size_bytes": 1,
            "sha256": "0" * 64,
        }, ROOT)
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            "index_anchor_path_mismatch" in item
            for item in result["failures"]
        ))

    def test_old_current_authority_is_stale_against_live_source(self):
        result = OLD_WRAPPER.load_and_resolve_current_authority(ROOT)
        self.assertFalse(result["validated_pass"])
        self.assertFalse(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v4_source_role_identity_mismatch:"
            "audit_tools/ros1_camera_only_atomic_launcher.py",
            result["failures"],
        )

    def test_system_orchestrator_hardlink_is_descriptor_bound_not_symlink_accepted(self):
        target = self.root / "system-orchestrator.exe"
        alias = self.root / "system-orchestrator-hardlink.exe"
        target.write_bytes(b"system executable fixture\n")
        alias.hardlink_to(target)
        identity = GENERATOR._absolute_regular_identity(alias)
        self.assertEqual(identity["path"], str(alias))
        self.assertGreaterEqual(identity["hardlink_count"], 2)
        self.assertEqual(
            identity["sha256"], hashlib.sha256(alias.read_bytes()).hexdigest(),
        )
        link = self.root / "system-orchestrator-symlink.exe"
        try:
            link.symlink_to(target)
        except OSError:
            return
        with self.assertRaises(GENERATOR.GenerationError):
            GENERATOR._absolute_regular_identity(link)


if __name__ == "__main__":
    unittest.main()
