"""Fail-closed tests for the versioned v7 BLOCKED_OFFLINE authority."""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from audit_tools import formal_admission_evidence_authority_v6 as WRAPPER
from audit_tools import formal_admission_evidence_authority_v6_core as CORE
from audit_tools import formal_admission_evidence_authority_v5 as OLD_WRAPPER
from audit_tools import generate_ros1_atomic_cli_field_producer_contract_blocked_offline_evidence_v1 as GENERATOR


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


class FormalAdmissionEvidenceAuthorityV6Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.doc_target = "audit_tools/test_ros1_machine_contract_doc_demotion.py"
        self.atomic_target = "audit_tools/test_ros1_camera_only_atomic_launcher.py"
        self.field_target = (
            "src/limo_cleanup_perception/test/"
            "test_ros1_noetic_field_readiness_exact_cli.py"
        )
        self.runner_target = CORE.UNITTEST_RUNNER
        self.test_id = CORE.DOC_DEMOTION_LINK_CASE_ID
        self.atomic_test_id = CORE.ATOMIC_SUPPORTING_TEST_ID
        self.field_test_id = CORE.FIELD_READINESS_SUPPORTING_TEST_ID
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
        _write(
            self.root, self.atomic_target,
            (
                "import unittest\n\n"
                "class Ros1CameraOnlyAtomicLauncherTest(unittest.TestCase):\n"
                "    def test_production_cli_is_blocked_until_runtime_admission_is_bound(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        _write(
            self.root, self.field_target,
            (
                "import unittest\n\n"
                "class Ros1NoeticFieldReadinessExactCliTest(unittest.TestCase):\n"
                "    def test_production_cli_blocks_on_unbound_producer_index_before_inputs(self):\n"
                "        self.assertTrue(True)\n"
            ).encode("utf-8"),
        )
        for relative in (
            "audit_tools/ros1_camera_runtime_import_probe.py",
            "audit_tools/ros1_camera_runtime_install_admission.py",
            "audit_tools/ros1_camera_only_atomic_launcher.py",
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "__init__.py"
            ),
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_semantic_evidence_producer.py"
            ),
            (
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_noetic_field_readiness.py"
            ),
        ):
            _write(self.root, relative, ("# " + relative + "\n").encode("utf-8"))
        _write(
            self.root, CORE.GENERATION_WRAPPER_SOURCE_PATH,
            b"PRODUCTION_INDEX_TRUST_ANCHOR = None\n",
        )
        _write(self.root, "overlay/a.py", b"VALUE = 1\n")

        self.predecessor_evidence_id = "fixture_predecessor_evidence"
        self.predecessor_generation_id = "fixture_predecessor_generation"
        self.predecessor_predecessor_evidence_id = (
            "fixture_predecessor_predecessor_evidence"
        )
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
                "predecessor_evidence_id": (
                    self.predecessor_predecessor_evidence_id
                ),
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
            ("atomic_test", "workspace", self.atomic_target),
            (
                "semantic_package_init", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "__init__.py",
            ),
            (
                "semantic_producer", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_semantic_evidence_producer.py",
            ),
            (
                "field_readiness", "workspace",
                "src/limo_cleanup_perception/limo_cleanup_perception/"
                "ros1_noetic_field_readiness.py",
            ),
            ("field_readiness_test", "workspace", self.field_target),
            ("predecessor_index", "workspace", "frozen/predecessor_index.json"),
            ("predecessor_report", "workspace", "frozen/predecessor_report.json"),
            ("predecessor_canonical", "workspace", "frozen/predecessor_canonical.json"),
        )
        suites = (
            {
                "suite_id": "machine_contract_doc_demotion",
                "root_role": "workspace",
                "target": self.doc_target,
                "runner": "unittest",
            },
            {
                "suite_id": "camera_only_atomic_launcher",
                "root_role": "workspace",
                "target": self.atomic_target,
                "runner": "unittest",
            },
            {
                "suite_id": "field_readiness_exact_cli",
                "root_role": "workspace",
                "target": self.field_target,
                "runner": "unittest",
            },
        )
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
            {
                "record_id": "atomic_wsl_python3",
                "suite_id": "camera_only_atomic_launcher",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python3_entry",
                "selection": "ALL",
            },
            {
                "record_id": "atomic_wsl_python314",
                "suite_id": "camera_only_atomic_launcher",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": "ALL",
            },
            {
                "record_id": "field_readiness_exact_cli_wsl_python314",
                "suite_id": "field_readiness_exact_cli",
                "platform": "POSIX_WSL",
                "interpreter_role": "system_python314_target",
                "selection": "ALL",
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
            predecessor_current_entry_predecessor_evidence_id=(
                self.predecessor_predecessor_evidence_id
            ),
            frozen_source_identities={},
            live_overlay_root="overlay",
            required_live_overlay_paths=("a.py",),
            host_perception_package_root=None,
            host_perception_package_files=(),
            host_perception_cache_files=(),
            allowed_empty_source_paths=(),
        )
        (self.root / "out").mkdir()
        self.source_roles = CORE.collect_source_role_bindings(
            self.root, self.policy,
        )
        self.logical = CORE.expected_logical_suite_records(
            self.root, self.source_roles, self.policy,
        )
        self.physical = sorted([
            self._physical_record(
                "doc_demotion_windows_bundled", "WINDOWS_HOST",
                "bundled_host_python", "machine_contract_doc_demotion",
                self.doc_target, self.test_id, passed=False,
            ),
            self._physical_record(
                "doc_demotion_link_posix_companion", "POSIX_WSL",
                "system_python314_target", "machine_contract_doc_demotion",
                self.doc_target, self.test_id, passed=True,
            ),
            self._physical_record(
                "atomic_wsl_python3", "POSIX_WSL",
                "system_python3_entry", "camera_only_atomic_launcher",
                self.atomic_target, self.atomic_test_id, passed=True,
            ),
            self._physical_record(
                "atomic_wsl_python314", "POSIX_WSL",
                "system_python314_target", "camera_only_atomic_launcher",
                self.atomic_target, self.atomic_test_id, passed=True,
            ),
            self._physical_record(
                "field_readiness_exact_cli_wsl_python314", "POSIX_WSL",
                "system_python314_target", "field_readiness_exact_cli",
                self.field_target, self.field_test_id, passed=True,
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
            "entry_lstat_size_bytes": (
                32 if role == "system_python3_entry"
                else (
                    CORE.PYTHON314_TARGET_IDENTITY["size_bytes"]
                    if role == "system_python314_target" else 4096
                )
            ),
            "entry_link_chain": entry_link_chain,
            "resolved_target": (
                deepcopy(CORE.PYTHON314_TARGET_IDENTITY)
                if role in (
                    "system_python3_entry", "system_python314_target")
                else {
                    "path": target_path,
                    "size_bytes": 4096,
                    "sha256": "1" * 64,
                    "regular_file": True,
                    "is_symlink": False,
                }
            ),
            "isolated": True,
            "no_bytecode": True,
            "version": (
                list(CORE.PYTHON314_VERSION)
                if role in (
                    "system_python3_entry", "system_python314_target")
                else [3, 14, 0]
            ),
        }

    @staticmethod
    def _orchestrator_identity():
        return {
            "path": r"C:\Windows\System32\wsl.exe",
            "size_bytes": 4096,
            "sha256": "2" * 64,
            "hardlink_count": 2,
        }

    def _physical_record(
        self, record_id, platform, interpreter_role, suite_id,
        test_target, test_id, passed,
    ):
        test_identity = self._source(test_target)
        runner_identity = self._source(self.runner_target)
        passed_ids = [test_id] if passed else []
        skipped_ids = [] if passed else [test_id]
        marker = {
            "path": test_target,
            "size_bytes": test_identity["size_bytes"],
            "sha256": test_identity["sha256"],
            "expected_ids": [test_id],
            "executed_ids": [test_id],
            "collected": 1,
            "passed": len(passed_ids),
            "failed": 0,
            "skipped": len(skipped_ids),
            "workspace_bytecode_policy": CORE.WORKSPACE_BYTECODE_POLICY,
            "workspace_pyc_bytes_read": 0,
            "workspace_pyc_attempts_blocked": [],
            "workspace_source_reads": [{
                "path": test_identity["path"],
                "size_bytes": test_identity["size_bytes"],
                "sha256": test_identity["sha256"],
            }],
            "workspace_loader_guard_restored": True,
            "workspace_pyc_audit_hook_active": True,
            "workspace_pyc_inode_policy": "WORKSPACE_PYC_SINGLE_LINK_INODE_V1",
            "workspace_pyc_inventory_count": 0,
            "workspace_pyc_inventory_stable": True,
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
            self.root, definition, suite, [test_id],
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
            "suite_id": suite_id,
            "platform": platform,
            "interpreter_role": interpreter_role,
            "test_artifact_identity": test_identity,
            "runner_artifact_identity": runner_identity,
            "interpreter_identity": interpreter_identity,
            "orchestrator_identity": orchestrator_identity,
            "expected_test_ids": [test_id],
            "executed_test_ids": [test_id],
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
            "external_wrapper_observation": None,
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
                environment = dict(CORE.CHILD_ENVIRONMENT)
                argv = CORE._expected_production_cli_argv(
                    self.root, definition, orchestrator_identity["path"],
                    self.source_roles,
                    interpreter_identity,
                )
            else:
                interpreter_identity = None
                orchestrator_identity = None
                argv = ["NOT_EXECUTED_SAFETY_BOUNDARY"]
                environment = {}
            if attempted:
                payload = CORE.expected_unbound_production_payload(definition)
            else:
                payload = {
                    "execution_attempted": False,
                    "supporting_test_id": definition["supporting_test_id"],
                    "supporting_record_ids": list(
                        definition["supporting_record_ids"]),
                    "blocked_code": definition["blocked_code"],
                }
            runtime_dependencies = []
            if attempted:
                for relative in CORE.production_runtime_dependency_paths(
                        definition):
                    identity = self._source(relative)
                    signature = CORE.source_runtime_signature(
                        self.root, "workspace", relative)
                    runtime_dependencies.append({
                        "path": relative,
                        "identity_before": deepcopy(identity),
                        "identity_after": deepcopy(identity),
                        "signature_before": deepcopy(signature),
                        "signature_after": deepcopy(signature),
                    })
            stdout = CORE.expected_production_observation_stdout(
                definition, payload)
            stderr = CORE.expected_production_observation_stderr(definition)
            result.append({
                "observation_id": definition["observation_id"],
                "source_identity_before": source,
                "source_identity_after": source,
                "runtime_dependencies": runtime_dependencies,
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
                "stdout": _stream(stdout),
                "stderr": _stream(stderr),
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
        return CORE.validate_formal_admission_evidence_authority_v6(
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
        result = CORE.load_and_resolve_formal_admission_evidence_authority_v6(
            self.root, identity, self.policy,
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertTrue(
            result["semantic_evidence_producer_contract_implemented"]
        )
        self.assertTrue(
            result["semantic_evidence_producer_offline_algorithm_validated"]
        )
        self.assertFalse(
            result["semantic_evidence_producer_production_authority_bound"]
        )
        self.assertFalse(
            result["semantic_evidence_producer_formal_evidence_admitted"]
        )
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
            result = CORE.load_and_resolve_formal_admission_evidence_authority_v6(
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
            self.assertIn("formal_authority_v6_current_count_invalid", result["failures"])

    def test_old_v6_entry_cannot_be_repromoted(self):
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

    def test_predecessor_current_entry_lineage_is_exact(self):
        predecessor = {
            "authority_id": CORE.AUTHORITY_FAMILY_ID,
            "index_instance_id": self.predecessor_index_identity[
                "index_instance_id"
            ],
            "generation_id": self.predecessor_generation_id,
            "current_evidence_id": self.predecessor_evidence_id,
            "accepted_by_formal_field_evidence_consumer": False,
            "authorizes_field_delivery": False,
            "entries": [{
                "evidence_id": self.predecessor_evidence_id,
                "predecessor_evidence_id": "wrong-lineage",
                "is_current": True,
            }],
        }
        failures = CORE._validate_predecessor_payload(
            predecessor, self.policy,
        )
        self.assertIn(
            "formal_authority_v6_predecessor_current_lineage_mismatch",
            failures,
        )

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
        self.assertIn("formal_authority_v6_source_role_set_invalid", result["failures"])

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
            "formal_authority_v6_child_artifacts_invalid", result["failures"]
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
        self.assertIn("formal_authority_v6_entry_invalid", result["failures"])

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
        original = path.read_bytes()
        path.write_bytes(original + b"# drift\n")
        result = self._validate()
        self.assertFalse(result["semantic_validated_pass"])
        self.assertTrue(any("source_role_identity_mismatch" in item for item in result["failures"]))
        path.write_bytes(original)

        definition = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "runtime_import_probe_unbound"
        )
        interpreter = self._interpreter_identity("system_python314_target")
        orchestrator = self._orchestrator_identity()
        wsl_path = Path(orchestrator["path"])
        payload = CORE.expected_unbound_production_payload(definition)
        completed = subprocess.CompletedProcess(
            [], definition["exit_code"],
            (
                definition["marker_prefix"].encode("ascii")
                + CORE._canonical_json(payload) + b"\n"
            ),
            b"",
        )
        outer = mock.patch.object(
            GENERATOR, "_outer_windows_environment",
            return_value={"SystemRoot": r"C:\Windows"},
        )
        with outer:
            observation = GENERATOR._run_production_cli(
                CORE, self.root, self.source_roles, definition,
                interpreter, orchestrator, wsl_path,
                _command_runner=lambda *unused_args, **unused_kwargs: completed,
            )
        cached = self._source(definition["source_path"])
        self.assertEqual(cached, observation["source_identity_before"])
        self.assertEqual(cached, observation["source_identity_after"])

        malformed_streams = (
            (completed.stdout[:-1], completed.stderr,
             "production_cli_stdout_mismatch:runtime_import_probe_unbound"),
            (completed.stdout + b"\n", completed.stderr,
             "production_cli_stdout_mismatch:runtime_import_probe_unbound"),
            (completed.stdout, b"unexpected stderr\n",
             "production_cli_stderr_mismatch:runtime_import_probe_unbound"),
        )
        for stdout, stderr, expected_error in malformed_streams:
            malformed = subprocess.CompletedProcess(
                [], definition["exit_code"], stdout, stderr)
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SystemRoot": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=lambda *unused_args, _value=malformed,
                        **unused_kwargs: _value,
                    )
            self.assertEqual(expected_error, str(raised.exception))

        for case, expected_error in (
            ("unknown", "production_payload_schema_invalid:"
             "runtime_import_probe_unbound"),
            ("elevated", "production_payload_semantic_mismatch:"
             "runtime_import_probe_unbound"),
        ):
            forged_payload = deepcopy(payload)
            if case == "unknown":
                forged_payload["unknown_elevation"] = True
            else:
                forged_payload["formal_consumer"] = True
            forged_stdout = (
                definition["marker_prefix"].encode("ascii")
                + CORE._canonical_json(forged_payload) + b"\n"
            )
            forged = subprocess.CompletedProcess(
                [], definition["exit_code"], forged_stdout, b"")
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SystemRoot": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=lambda *unused_args, _value=forged,
                        **unused_kwargs: _value,
                    )
            self.assertEqual(expected_error, str(raised.exception))

        replacement = path.with_name("runtime-probe-replacement.py")
        replacement.write_bytes(b"X" * len(original))
        os.replace(replacement, path)
        calls = []
        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SystemRoot": r"C:\Windows"}):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "production_cli_source_identity_mismatch_before:"
                    "runtime_import_probe_unbound"):
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, definition,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=lambda *args, **kwargs: calls.append(
                        (args, kwargs)),
                )
        self.assertEqual([], calls)
        path.write_bytes(original)

        def drift_then_restore(*unused_args, **unused_kwargs):
            path.write_bytes(original + b"# transient drift\n")
            path.write_bytes(original)
            metadata = path.stat()
            os.utime(
                path,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
            )
            return completed

        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SystemRoot": r"C:\Windows"}):
            with self.assertRaises(GENERATOR.GenerationError) as raised:
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, definition,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=drift_then_restore,
                )
        self.assertEqual(
            "production_cli_source_runtime_drift:runtime_import_probe_unbound",
            str(raised.exception),
        )

        persistent_calls = []
        def drift_without_restore(*unused_args, **unused_kwargs):
            persistent_calls.append(True)
            path.write_bytes(original + b"# persistent drift\n")
            return completed

        try:
            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SystemRoot": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, definition,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=drift_without_restore,
                    )
            self.assertEqual(
                "production_cli_source_identity_mismatch_after:"
                "runtime_import_probe_unbound",
                str(raised.exception),
            )
            self.assertEqual([True], persistent_calls)
        finally:
            path.write_bytes(original)

        semantic = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "semantic_producer_authority_unbound"
        )
        semantic_payload = CORE.expected_unbound_production_payload(semantic)
        semantic_success_completed = subprocess.CompletedProcess(
            [], semantic["exit_code"],
            CORE._canonical_json(semantic_payload) + b"\n",
            b"",
        )
        dependency_paths = (
            "src/limo_cleanup_perception/limo_cleanup_perception/__init__.py",
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_noetic_field_readiness.py",
        )
        for dependency_relative in dependency_paths:
            dependency_path = self.root.joinpath(
                *dependency_relative.split("/"))
            dependency_original = dependency_path.read_bytes()
            dependency_before_code = (
                "production_cli_runtime_dependency_identity_mismatch_before:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )
            dependency_after_code = (
                "production_cli_runtime_dependency_identity_mismatch_after:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )
            dependency_runtime_code = (
                "production_cli_runtime_dependency_runtime_drift:"
                "semantic_producer_authority_unbound:"
                + dependency_relative
            )

            calls = []
            dependency_path.write_bytes(
                dependency_original + b"# dependency before drift\n")
            try:
                with mock.patch.object(
                        GENERATOR, "_outer_windows_environment",
                        return_value={"SystemRoot": r"C:\Windows"}):
                    with self.assertRaises(
                            GENERATOR.GenerationError) as raised:
                        GENERATOR._run_production_cli(
                            CORE, self.root, self.source_roles, semantic,
                            interpreter, orchestrator, wsl_path,
                            _command_runner=lambda *args, **kwargs:
                            calls.append((args, kwargs)),
                        )
                self.assertEqual(dependency_before_code, str(raised.exception))
                self.assertEqual([], calls)
            finally:
                dependency_path.write_bytes(dependency_original)

            persistent_calls = []
            def dependency_drift_without_restore(
                    *unused_args, **unused_kwargs):
                persistent_calls.append(True)
                dependency_path.write_bytes(
                    dependency_original + b"# dependency persistent drift\n")
                return semantic_success_completed

            try:
                with mock.patch.object(
                        GENERATOR, "_outer_windows_environment",
                        return_value={"SystemRoot": r"C:\Windows"}):
                    with self.assertRaises(
                            GENERATOR.GenerationError) as raised:
                        GENERATOR._run_production_cli(
                            CORE, self.root, self.source_roles, semantic,
                            interpreter, orchestrator, wsl_path,
                            _command_runner=dependency_drift_without_restore,
                        )
                self.assertEqual(dependency_after_code, str(raised.exception))
                self.assertEqual([True], persistent_calls)
            finally:
                dependency_path.write_bytes(dependency_original)

            transient_calls = []
            def dependency_drift_then_restore(
                    *unused_args, **unused_kwargs):
                transient_calls.append(True)
                dependency_path.write_bytes(
                    dependency_original + b"# dependency transient drift\n")
                dependency_path.write_bytes(dependency_original)
                metadata = dependency_path.stat()
                os.utime(
                    dependency_path,
                    ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
                )
                return semantic_success_completed

            with mock.patch.object(
                    GENERATOR, "_outer_windows_environment",
                    return_value={"SystemRoot": r"C:\Windows"}):
                with self.assertRaises(GENERATOR.GenerationError) as raised:
                    GENERATOR._run_production_cli(
                        CORE, self.root, self.source_roles, semantic,
                        interpreter, orchestrator, wsl_path,
                        _command_runner=dependency_drift_then_restore,
                    )
            self.assertEqual(dependency_runtime_code, str(raised.exception))
            self.assertEqual([True], transient_calls)

        semantic_completed = subprocess.CompletedProcess(
            [], semantic["exit_code"],
            CORE._canonical_json(semantic_payload) + b"\n",
            b"unexpected stderr\n",
        )
        with mock.patch.object(
                GENERATOR, "_outer_windows_environment",
                return_value={"SystemRoot": r"C:\Windows"}):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "production_cli_stderr_mismatch:"
                    "semantic_producer_authority_unbound"):
                GENERATOR._run_production_cli(
                    CORE, self.root, self.source_roles, semantic,
                    interpreter, orchestrator, wsl_path,
                    _command_runner=lambda *unused_args, **unused_kwargs:
                    semantic_completed,
                )

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
        result = CORE.validate_formal_admission_evidence_authority_v6(
            self.root, self.payload, bad_policy,
        )
        self.assertIn(
            "formal_authority_v6_policy_nonformal_diagnostic_forbidden",
            result["failures"],
        )

    def test_logical_denominator_is_recomputed_from_ast(self):
        self.assertEqual(len(self.logical), 3)
        self.assertEqual(
            {item["suite_id"] for item in self.logical},
            {
                "machine_contract_doc_demotion",
                "camera_only_atomic_launcher",
                "field_readiness_exact_cli",
            },
        )
        self.assertTrue(all(item["collected"] == 1 for item in self.logical))
        self._replace_report(
            lambda value: value["test_matrix"].update(
                logical_expected_total=187,
            )
        )
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_report_test_count_mismatch:logical_expected_total",
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

        for mode in ("missing", "wrong", "duplicate"):
            def tamper_distro(report, mode=mode):
                record = next(
                    item for item in report["test_matrix"][
                        "physical_execution_records"]
                    if item["record_id"] == "atomic_wsl_python314"
                )
                index = record["argv"].index("--distribution")
                if mode == "missing":
                    del record["argv"][index:index + 2]
                elif mode == "wrong":
                    record["argv"][index + 1] = "Debian"
                else:
                    record["argv"][index:index] = [
                        "--distribution", CORE.WSL_DISTRIBUTION,
                    ]
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_distro)
            result = self._validate()
            self.assertIn(
                "formal_authority_v6_physical_argv_mismatch:"
                "atomic_wsl_python314",
                result["failures"],
            )

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

        def tamper_static_record_id(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "field_readiness_production_cli_unbound"
            )
            item["payload"]["supporting_record_ids"] = [
                "atomic_wsl_python314",
            ]
            item["payload_sha256"] = _sha(item["payload"])

        self._replace_report(tamper_static_record_id)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_static_observation_payload_invalid:"
            "field_readiness_production_cli_unbound",
            result["failures"],
        )
        self.tearDown()
        self.setUp()

        def remove_supporting_pass(report):
            record = next(
                item for item in report["test_matrix"][
                    "physical_execution_records"
                ]
                if item["record_id"]
                == "field_readiness_exact_cli_wsl_python314"
            )
            record["passed_ids"] = []

        self._replace_report(remove_supporting_pass)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_static_observation_"
            "supporting_record_invalid:"
            "field_readiness_production_cli_unbound:"
            "field_readiness_exact_cli_wsl_python314",
            result["failures"],
        )

        dependency_path = (
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_noetic_field_readiness.py"
        )
        for case in ("missing", "extra", "duplicate"):
            self.tearDown()
            self.setUp()

            def tamper_dependencies(report, case=case):
                item = next(
                    record for record in report["production_cli_observations"]
                    if record["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                dependencies = item["runtime_dependencies"]
                if case == "missing":
                    dependencies[:] = [
                        entry for entry in dependencies
                        if entry["path"] != dependency_path
                    ]
                elif case == "extra":
                    extra = deepcopy(dependencies[0])
                    extra["path"] = "src/extra_runtime_dependency.py"
                    dependencies.append(extra)
                else:
                    duplicate = next(
                        deepcopy(entry) for entry in dependencies
                        if entry["path"] == dependency_path
                    )
                    dependencies.append(duplicate)

            self._replace_report(tamper_dependencies)
            result = self._validate()
            expected_code = {
                "missing": (
                    "formal_authority_v6_production_dependency_missing:"
                    "semantic_producer_authority_unbound:" + dependency_path
                ),
                "extra": (
                    "formal_authority_v6_production_dependency_extra:"
                    "semantic_producer_authority_unbound:"
                    "src/extra_runtime_dependency.py"
                ),
                "duplicate": (
                    "formal_authority_v6_production_dependency_duplicate:"
                    "semantic_producer_authority_unbound:" + dependency_path
                ),
            }[case]
            self.assertIn(expected_code, result["failures"])

        self.tearDown()
        self.setUp()
        def reorder_dependencies(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            item["runtime_dependencies"].reverse()

        self._replace_report(reorder_dependencies)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_dependency_order_invalid:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def forge_bound_dependency_material(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            dependency = next(
                entry for entry in item["runtime_dependencies"]
                if entry["path"] == item["source_identity_before"]["path"]
            )
            forged_identity = deepcopy(dependency["identity_before"])
            forged_identity["size_bytes"] += 1
            forged_identity["sha256"] = "f" * 64
            dependency["identity_before"] = deepcopy(forged_identity)
            dependency["identity_after"] = deepcopy(forged_identity)
            forged_signature = deepcopy(dependency["signature_before"])
            forged_signature[-1]["size_bytes"] += 1
            dependency["signature_before"] = deepcopy(forged_signature)
            dependency["signature_after"] = deepcopy(forged_signature)
            item["source_identity_before"] = deepcopy(forged_identity)
            item["source_identity_after"] = deepcopy(forged_identity)

        self._replace_report(forge_bound_dependency_material)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_dependency_identity_mismatch:"
            "semantic_producer_authority_unbound:"
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_semantic_evidence_producer.py:before",
            result["failures"],
        )
        self.assertIn(
            "formal_authority_v6_production_dependency_signature_mismatch:"
            "semantic_producer_authority_unbound:"
            "src/limo_cleanup_perception/limo_cleanup_perception/"
            "ros1_semantic_evidence_producer.py:before",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def add_static_dependencies(report):
            semantic = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            static = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "atomic_runtime_admission_unbound"
            )
            static["runtime_dependencies"] = [
                deepcopy(semantic["runtime_dependencies"][0])]

        self._replace_report(add_static_dependencies)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_static_observation_runtime_"
            "dependencies_forbidden:atomic_runtime_admission_unbound",
            result["failures"],
        )

        self.tearDown()
        self.setUp()
        def split_top_level_source(report):
            item = next(
                record for record in report["production_cli_observations"]
                if record["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            item["source_identity_before"] = deepcopy(
                item["runtime_dependencies"][1]["identity_before"])

        self._replace_report(split_top_level_source)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_source_dependency_split:"
            "semantic_producer_authority_unbound:before",
            result["failures"],
        )

    def test_wrong_production_blocked_code_is_rejected(self):
        executed = {
            item["observation_id"]: item
            for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["execution_attempted"]
        }
        self.assertEqual(
            {
                observation_id: len(
                    CORE.expected_unbound_production_payload(definition))
                for observation_id, definition in executed.items()
            },
            {
                "runtime_import_probe_unbound": 23,
                "runtime_install_authority_unbound": 46,
                "semantic_producer_authority_unbound": 13,
            },
        )

        def sync_payload_stream(record, definition):
            record["payload_sha256"] = _sha(record["payload"])
            prefix = definition["marker_prefix"]
            raw = CORE._canonical_json(record["payload"]) + b"\n"
            if prefix is not None:
                raw = prefix.encode("ascii") + raw
            record["stdout"] = _stream(raw)

        for observation_id, definition in executed.items():
            def add_upgrade_and_unknown(report, observation_id=observation_id,
                                        definition=definition):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"] == observation_id)
                record["payload"].update({
                    "formal_acceptance": True,
                    "formal_consumer": True,
                    "field_evidence_admitted": True,
                    "authorizes_field_delivery": True,
                    "unknown_elevation": True,
                })
                sync_payload_stream(record, definition)

            self._replace_report(add_upgrade_and_unknown)
            result = self._validate()
            self.assertIn(
                "formal_authority_v6_production_payload_schema_invalid:"
                + observation_id,
                result["failures"],
            )
            self.assertIn(
                "formal_authority_v6_production_stdout_mismatch:"
                + observation_id,
                result["failures"],
            )

        upgrade_field = {
            "runtime_import_probe_unbound": "formal_consumer",
            "runtime_install_authority_unbound": "formal_acceptance",
            "semantic_producer_authority_unbound": "formal_acceptance",
        }
        for observation_id, field in upgrade_field.items():
            definition = executed[observation_id]

            def elevate_known_flag(report, observation_id=observation_id,
                                   definition=definition, field=field):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"] == observation_id)
                record["payload"][field] = True
                sync_payload_stream(record, definition)

            self._replace_report(elevate_known_flag)
            result = self._validate()
            self.assertIn(
                "formal_authority_v6_production_payload_semantic_mismatch:"
                + observation_id,
                result["failures"],
            )

        def wrong_type(report):
            observation_id = "semantic_producer_authority_unbound"
            definition = executed[observation_id]
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"] == observation_id)
            record["payload"]["delivery_ready"] = 0
            sync_payload_stream(record, definition)

        self._replace_report(wrong_type)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_payload_schema_invalid:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

    def test_semantic_producer_unbound_observation_is_exact_and_nonformal(self):
        expected = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"] == "semantic_producer_authority_unbound"
        )
        self.assertEqual(
            expected["blocked_code"],
            "semantic_producer_production_authority_not_anchored",
        )
        self.assertIn(
            "FORMAL_SEMANTIC_EVIDENCE_PRODUCER_PRODUCTION_AUTHORITY_NOT_BOUND",
            CORE.GATE_STATE["active_blockers"],
        )
        self.assertFalse(
            CORE.GATE_STATE[
                "semantic_evidence_producer_production_authority_bound"
            ]
        )
        self.assertFalse(
            CORE.GATE_STATE[
                "semantic_evidence_producer_formal_evidence_admitted"
            ]
        )
        semantic_record = next(
            item for item in self.observations
            if item["observation_id"]
            == "semantic_producer_authority_unbound"
        )
        wsl_root = CORE._execution_workspace_path(self.root)
        source_root = wsl_root.rstrip("/") + "/" + (
            CORE.PRODUCTION_PACKAGE_SOURCE_ROOT
        )
        target = wsl_root.rstrip("/") + "/" + expected["source_path"]
        bootstrap_index = semantic_record["argv"].index(
            CORE.PRODUCTION_PACKAGE_BOOTSTRAP
        )
        distribution_index = semantic_record["argv"].index("--distribution")
        self.assertEqual(
            CORE.WSL_DISTRIBUTION,
            semantic_record["argv"][distribution_index + 1],
        )
        self.assertEqual("-c", semantic_record["argv"][bootstrap_index - 1])
        self.assertEqual(source_root, semantic_record["argv"][bootstrap_index + 1])
        self.assertEqual(target, semantic_record["argv"][bootstrap_index + 2])
        expected_manifest = CORE.production_runtime_dependency_manifest(
            self.source_roles, expected)
        manifest_json = semantic_record["argv"][bootstrap_index + 3]
        self.assertEqual(
            expected_manifest, json.loads(manifest_json),
        )
        self.assertEqual(
            _sha(expected_manifest),
            semantic_record["argv"][bootstrap_index + 4],
        )
        expected_interpreter_manifest = {
            key: CORE.PYTHON314_TARGET_IDENTITY[key]
            for key in ("path", "size_bytes", "sha256")
        }
        interpreter_manifest_json = semantic_record["argv"][
            bootstrap_index + 5]
        self.assertEqual(
            expected_interpreter_manifest,
            json.loads(interpreter_manifest_json),
        )
        self.assertEqual(
            _sha(expected_interpreter_manifest),
            semantic_record["argv"][bootstrap_index + 6],
        )
        self.assertEqual(
            list(CORE.SEMANTIC_PRODUCTION_RUNTIME_DEPENDENCY_PATHS),
            [item["path"] for item in semantic_record["runtime_dependencies"]],
        )
        for item in semantic_record["runtime_dependencies"]:
            expected_identity = self._source(item["path"])
            expected_signature = CORE.source_runtime_signature(
                self.root, "workspace", item["path"])
            self.assertEqual(expected_identity, item["identity_before"])
            self.assertEqual(expected_identity, item["identity_after"])
            self.assertEqual(expected_signature, item["signature_before"])
            self.assertEqual(expected_signature, item["signature_after"])
        self.assertEqual(1, semantic_record["argv"].count(source_root))
        self.assertEqual(
            semantic_record["argv_sha256"], _sha(semantic_record["argv"]),
        )
        self.assertEqual(dict(CORE.EMPTY_STREAM_IDENTITY), semantic_record["stderr"])
        self.assertEqual(
            _stream(CORE.expected_production_observation_stdout(
                expected, semantic_record["payload"])),
            semantic_record["stdout"],
        )
        self.assertTrue(semantic_record["execution_attempted"])
        self.assertTrue(semantic_record["not_in_logical_denominator"])
        self.assertTrue(semantic_record["not_in_physical_denominator"])
        self.assertFalse(semantic_record["formal_consumer"])
        self.assertFalse(semantic_record["delivery_ready"])

        field_expected = next(
            item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
            if item["observation_id"]
            == "field_readiness_production_cli_unbound"
        )
        self.assertFalse(field_expected["execution_attempted"])
        self.assertEqual(
            field_expected["blocked_code"],
            "semantic_producer_production_authority_not_anchored",
        )
        self.assertEqual(
            field_expected["supporting_test_id"],
            CORE.FIELD_READINESS_SUPPORTING_TEST_ID,
        )
        self.assertEqual(
            field_expected["supporting_record_ids"],
            ("field_readiness_exact_cli_wsl_python314",),
        )
        field_record = next(
            item for item in self.observations
            if item["observation_id"]
            == "field_readiness_production_cli_unbound"
        )
        self.assertEqual(["NOT_EXECUTED_SAFETY_BOUNDARY"], field_record["argv"])
        self.assertTrue(field_record["not_in_logical_denominator"])
        self.assertTrue(field_record["not_in_physical_denominator"])
        self.assertFalse(field_record["formal_consumer"])
        self.assertFalse(field_record["delivery_ready"])

        if os.name != "nt":
            actual_source_roles = [
                CORE.source_artifact_identity(ROOT, "workspace", relative)
                for relative in CORE.production_runtime_dependency_paths(
                    expected)
            ]
            actual_argv = CORE._expected_production_cli_argv(
                ROOT, expected, "wsl.exe", actual_source_roles,
                self._interpreter_identity("system_python314_target"),
            )
            child = actual_argv[actual_argv.index("--exec") + 1:]

            def run_child(argv):
                return subprocess.run(
                    argv, cwd=str(ROOT), env={}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=30.0,
                )

            completed = run_child(child)
            self.assertEqual(1, completed.returncode)
            self.assertEqual(b"", completed.stderr)
            child_payload = json.loads(completed.stdout.decode("utf-8"))
            self.assertEqual(
                CORE.expected_unbound_production_payload(expected),
                child_payload,
            )
            self.assertEqual(
                ["semantic_producer_production_authority_not_anchored"],
                child_payload["failures"],
            )
            self.assertFalse(child_payload["producer_material_validated"])
            self.assertFalse(child_payload["formal_acceptance"])
            self.assertTrue(child_payload["not_in_four_scene_denominator"])
            self.assertFalse(child_payload["delivery_ready"])

            python_index = child.index("/usr/bin/python3.14")
            actual_target = child[child.index(
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP) + 2]
            bare = [
                *child[:python_index + 1], "-I", "-S", "-B",
                actual_target, *expected["argv_suffix"],
            ]
            bare_completed = run_child(bare)
            self.assertNotEqual(0, bare_completed.returncode)
            self.assertIn(b"ModuleNotFoundError", bare_completed.stderr)

            child_bootstrap_index = child.index(
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP
            )
            root_index = child_bootstrap_index + 1
            target_index = child_bootstrap_index + 2
            wrong_root = list(child)
            wrong_root[root_index] = (
                "/tmp/forbidden/src/limo_cleanup_perception"
            )
            self.assertEqual(94, run_child(wrong_root).returncode)
            wrong_target = list(child)
            wrong_target[target_index] = (
                child[root_index]
                + "/limo_cleanup_perception/ros1_noetic_field_readiness.py"
            )
            self.assertEqual(94, run_child(wrong_target).returncode)

            ambient = list(child)
            ambient[child_bootstrap_index] = (
                "import sys;sys.path.append({!r});exec({!r})".format(
                    str(ROOT), CORE.PRODUCTION_PACKAGE_BOOTSTRAP,
                )
            )
            self.assertEqual(95, run_child(ambient).returncode)
            preloaded = list(child)
            preloaded[child_bootstrap_index] = (
                "import sys,types;"
                "_m=types.ModuleType('limo_cleanup_perception."
                "ros1_semantic_evidence_producer');"
                "_m.__file__='/tmp/fake.py';"
                "_m.__spec__=types.SimpleNamespace(origin='/tmp/fake.py');"
                "sys.modules[_m.__name__]=_m;exec({!r})".format(
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP,
                )
            )
            self.assertEqual(97, run_child(preloaded).returncode)

            manifest_index = child_bootstrap_index + 3
            manifest_sha_index = child_bootstrap_index + 4
            wrong_manifest_digest = list(child)
            wrong_manifest_digest[manifest_sha_index] = "0" * 64
            self.assertEqual(102, run_child(wrong_manifest_digest).returncode)

            wrong_manifest_bytes = list(child)
            manifest = json.loads(wrong_manifest_bytes[manifest_index])
            manifest[0]["size_bytes"] += 1
            wrong_manifest_bytes[manifest_index] = (
                CORE._canonical_json(manifest).decode("utf-8"))
            wrong_manifest_bytes[manifest_sha_index] = _sha(manifest)
            self.assertEqual(104, run_child(wrong_manifest_bytes).returncode)

            interpreter_manifest_index = child_bootstrap_index + 5
            interpreter_manifest_sha_index = child_bootstrap_index + 6
            wrong_interpreter_digest = list(child)
            wrong_interpreter_digest[interpreter_manifest_sha_index] = "0" * 64
            self.assertEqual(
                106, run_child(wrong_interpreter_digest).returncode)
            wrong_interpreter_path = list(child)
            interpreter_manifest = json.loads(
                wrong_interpreter_path[interpreter_manifest_index])
            interpreter_manifest["path"] = "/usr/bin/python3"
            wrong_interpreter_path[interpreter_manifest_index] = (
                CORE._canonical_json(interpreter_manifest).decode("utf-8"))
            wrong_interpreter_path[interpreter_manifest_sha_index] = _sha(
                interpreter_manifest)
            self.assertEqual(106, run_child(wrong_interpreter_path).returncode)
            wrong_interpreter_hash = list(child)
            interpreter_manifest = json.loads(
                wrong_interpreter_hash[interpreter_manifest_index])
            interpreter_manifest["sha256"] = "0" * 64
            wrong_interpreter_hash[interpreter_manifest_index] = (
                CORE._canonical_json(interpreter_manifest).decode("utf-8"))
            wrong_interpreter_hash[interpreter_manifest_sha_index] = _sha(
                interpreter_manifest)
            self.assertEqual(107, run_child(wrong_interpreter_hash).returncode)

            importlib_hook = list(child)
            importlib_hook[child_bootstrap_index] = (
                "import importlib;"
                "importlib.import_module=lambda *args,**kwargs:"
                "(_ for _ in ()).throw(SystemExit(88));"
                "exec({!r})".format(CORE.PRODUCTION_PACKAGE_BOOTSTRAP)
            )
            importlib_hook_completed = run_child(importlib_hook)
            self.assertEqual(1, importlib_hook_completed.returncode)
            self.assertEqual(b"", importlib_hook_completed.stderr)
            self.assertEqual(
                ["semantic_producer_production_authority_not_anchored"],
                json.loads(importlib_hook_completed.stdout.decode("utf-8"))[
                    "failures"],
            )

            wrong_package_origin = list(child)
            wrong_package_origin[child_bootstrap_index] = (
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP.replace(
                    "_attest(_package,_package_init_path)\n",
                    "_package.__file__='/tmp/fake.py'\n"
                    "_attest(_package,_package_init_path)\n",
                )
            )
            self.assertEqual(99, run_child(wrong_package_origin).returncode)

            wrong_package_path = list(child)
            wrong_package_path[child_bootstrap_index] = (
                CORE.PRODUCTION_PACKAGE_BOOTSTRAP.replace(
                    "if list(getattr(_package,'__path__',())) != "
                    "[_package_directory]: raise SystemExit(101)\n",
                    "_package.__path__=['/tmp/fake-package']\n"
                    "if list(getattr(_package,'__path__',())) != "
                    "[_package_directory]: raise SystemExit(101)\n",
                )
            )
            self.assertEqual(101, run_child(wrong_package_path).returncode)

            for direct_id in (
                    "runtime_import_probe_unbound",
                    "runtime_install_authority_unbound"):
                direct_definition = next(
                    item for item in CORE.PRODUCTION_CLI_EXPECTATIONS
                    if item["observation_id"] == direct_id
                )
                direct_roles = [CORE.source_artifact_identity(
                    ROOT, "workspace", direct_definition["source_path"])]
                direct_argv = CORE._expected_production_cli_argv(
                    ROOT, direct_definition, "wsl.exe", direct_roles,
                    self._interpreter_identity("system_python314_target"),
                )
                direct_child = direct_argv[
                    direct_argv.index("--exec") + 1:]
                direct_bootstrap_index = direct_child.index(
                    CORE.PRODUCTION_SCRIPT_BOOTSTRAP)
                self.assertEqual(
                    "-c", direct_child[direct_bootstrap_index - 1])
                self.assertEqual(
                    direct_definition["source_path"],
                    json.loads(direct_child[direct_bootstrap_index + 3])[
                        0]["path"],
                )
                direct_completed = run_child(direct_child)
                self.assertEqual(
                    direct_definition["exit_code"],
                    direct_completed.returncode,
                )
                marker = direct_definition["marker_prefix"].encode("ascii")
                marker_lines = [
                    line for line in direct_completed.stdout.splitlines()
                    if line.startswith(marker)
                ]
                self.assertEqual(
                    1, len(marker_lines),
                    (direct_id, direct_completed.stdout,
                     direct_completed.stderr, direct_completed.returncode),
                )
                direct_payload = json.loads(
                    marker_lines[0][len(marker):].decode("utf-8"))
                self.assertEqual(
                    CORE.expected_unbound_production_payload(
                        direct_definition),
                    direct_payload,
                )
                self.assertEqual(
                    [direct_definition["blocked_code"]],
                    direct_payload["failures"],
                )
                direct_wrong_digest = list(direct_child)
                direct_wrong_digest[direct_bootstrap_index + 4] = "0" * 64
                self.assertEqual(
                    102, run_child(direct_wrong_digest).returncode)
                direct_wrong_bytes = list(direct_child)
                direct_manifest = json.loads(
                    direct_wrong_bytes[direct_bootstrap_index + 3])
                direct_manifest[0]["size_bytes"] += 1
                direct_wrong_bytes[direct_bootstrap_index + 3] = (
                    CORE._canonical_json(direct_manifest).decode("utf-8"))
                direct_wrong_bytes[direct_bootstrap_index + 4] = _sha(
                    direct_manifest)
                self.assertEqual(
                    104, run_child(direct_wrong_bytes).returncode)
                direct_wrong_interpreter_digest = list(direct_child)
                direct_wrong_interpreter_digest[
                    direct_bootstrap_index + 6] = "0" * 64
                self.assertEqual(
                    106,
                    run_child(direct_wrong_interpreter_digest).returncode,
                )
                direct_wrong_interpreter_hash = list(direct_child)
                direct_interpreter_manifest = json.loads(
                    direct_wrong_interpreter_hash[
                        direct_bootstrap_index + 5])
                direct_interpreter_manifest["sha256"] = "0" * 64
                direct_wrong_interpreter_hash[
                    direct_bootstrap_index + 5] = CORE._canonical_json(
                        direct_interpreter_manifest).decode("utf-8")
                direct_wrong_interpreter_hash[
                    direct_bootstrap_index + 6] = _sha(
                        direct_interpreter_manifest)
                self.assertEqual(
                    107, run_child(direct_wrong_interpreter_hash).returncode)

        def tamper_marker(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["payload"]["marker"] = "WRONG"
            record["payload_sha256"] = _sha(record["payload"])

        self._replace_report(tamper_marker)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_payload_semantic_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def tamper_argv(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["argv"] = record["argv"][:-2]
            record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(tamper_argv)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_argv_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        for mode in ("missing", "wrong", "duplicate"):
            def tamper_production_distro(report, mode=mode):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                index = record["argv"].index("--distribution")
                if mode == "missing":
                    del record["argv"][index:index + 2]
                elif mode == "wrong":
                    record["argv"][index + 1] = "Debian"
                else:
                    record["argv"][index:index] = [
                        "--distribution", CORE.WSL_DISTRIBUTION,
                    ]
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_production_distro)
            result = self._validate()
            self.assertIn(
                "formal_authority_v6_production_argv_mismatch:"
                "semantic_producer_authority_unbound",
                result["failures"],
            )

        def tamper_bootstrap(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            index = record["argv"].index(CORE.PRODUCTION_PACKAGE_BOOTSTRAP)
            record["argv"][index] += "# drift"
            record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(tamper_bootstrap)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_argv_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        for offset, replacement in (
            (1, "/tmp/substitute/src/limo_cleanup_perception"),
            (2, "/tmp/substitute/producer.py"),
        ):
            def tamper_bound_path(report, offset=offset, replacement=replacement):
                record = next(
                    item for item in report["production_cli_observations"]
                    if item["observation_id"]
                    == "semantic_producer_authority_unbound"
                )
                index = record["argv"].index(
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP
                )
                record["argv"][index + offset] = replacement
                record["argv_sha256"] = _sha(record["argv"])

            self._replace_report(tamper_bound_path)
            result = self._validate()
            self.assertIn(
                "formal_authority_v6_production_argv_mismatch:"
                "semantic_producer_authority_unbound",
                result["failures"],
            )

        def tamper_stderr(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["stderr"] = _stream(b"unexpected stderr\n")

        self._replace_report(tamper_stderr)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_stderr_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def tamper_stdout(report):
            record = next(
                item for item in report["production_cli_observations"]
                if item["observation_id"]
                == "semantic_producer_authority_unbound"
            )
            record["stdout"] = _stream(b"forged canonical-looking stream\n")

        self._replace_report(tamper_stdout)
        result = self._validate()
        self.assertIn(
            "formal_authority_v6_production_stdout_mismatch:"
            "semantic_producer_authority_unbound",
            result["failures"],
        )

        def synchronously_forge_interpreter(report):
            forged = self._interpreter_identity("system_python314_target")
            forged["entry_lstat_size_bytes"] += 1
            forged["resolved_target"]["size_bytes"] += 1
            forged["resolved_target"]["sha256"] = "f" * 64
            for record in report["test_matrix"]["physical_execution_records"]:
                identity = record["interpreter_identity"]
                if record["interpreter_role"] in (
                        "system_python3_entry", "system_python314_target"):
                    replacement = deepcopy(forged)
                    if record["interpreter_role"] == "system_python3_entry":
                        replacement["entry_path"] = "/usr/bin/python3"
                        replacement["entry_is_symlink"] = True
                        replacement["entry_lstat_size_bytes"] = 32
                        replacement["entry_link_chain"] = [{
                            "path": "/usr/bin/python3", "target": "python3.14",
                        }]
                    record["interpreter_identity"] = replacement
                    record["marker_payload"]["executable"] = deepcopy(
                        replacement)
                    record["marker_payload_sha256"] = _sha(
                        record["marker_payload"])
            for record in report["production_cli_observations"]:
                if record["execution_attempted"] is not True:
                    continue
                record["interpreter_identity"] = deepcopy(forged)
                bootstrap = (
                    CORE.PRODUCTION_PACKAGE_BOOTSTRAP
                    if CORE.PRODUCTION_PACKAGE_BOOTSTRAP in record["argv"]
                    else CORE.PRODUCTION_SCRIPT_BOOTSTRAP
                )
                index = record["argv"].index(bootstrap)
                manifest = {
                    key: forged["resolved_target"][key]
                    for key in ("path", "size_bytes", "sha256")
                }
                record["argv"][index + 5] = CORE._canonical_json(
                    manifest).decode("utf-8")
                record["argv"][index + 6] = _sha(manifest)
                record["argv_sha256"] = _sha(record["argv"])

        self._replace_report(synchronously_forge_interpreter)
        result = self._validate()
        self.assertTrue(any(
            failure.endswith("_target_anchor_mismatch")
            for failure in result["failures"]
        ), result["failures"])

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

        noncollision.unlink()
        nested = evidence / "nested-collision.json"
        nested.write_bytes(_json_bytes({
            "entries": [{"evidence_id": CORE.CURRENT_EVIDENCE_ID}],
        }))
        inventory, collisions = GENERATOR._evidence_identity_inventory(
            CORE, self.root,
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(collisions, [{
            "path": "evidence/nested-collision.json",
            "field": "entries[0].evidence_id",
            "value": CORE.CURRENT_EVIDENCE_ID,
        }])

        nested.unlink()
        abandoned = evidence / "abandoned" / "partial.json"
        abandoned.parent.mkdir()
        abandoned.write_bytes(b"")
        abandoned_relative = abandoned.relative_to(self.root).as_posix()
        abandoned_identity = {
            "path": abandoned_relative,
            "size_bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
        registry_entry = {
            "schema_version": "registered_nonselectable_generation/v1",
            "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
            "generation_status": "ABANDONED_UNINDEXED",
            "generation_id": "historical-abandoned-generation",
            "index_instance_id": "historical-abandoned-index-instance",
            "artifacts": [{
                "role": "canonical",
                **abandoned_identity,
            }],
        }
        with mock.patch.object(
            GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
            (registry_entry,),
        ):
            inventory, collisions = GENERATOR._evidence_identity_inventory(
                CORE, self.root,
            )
        registered = next(
            item for item in inventory if item["path"] == abandoned_relative
        )
        self.assertEqual(collisions, [])
        self.assertFalse(registered["strict_json_readable"])
        self.assertEqual(
            registered["registry_generation_status"],
            "ABANDONED_UNINDEXED",
        )
        self.assertEqual(registered["registry_artifact_role"], "canonical")

        parseable = evidence / "abandoned" / "report.json"
        parseable.write_bytes(_json_bytes({
            "generation_id": "historical-abandoned-generation",
        }))
        parseable_relative = parseable.relative_to(self.root).as_posix()
        parseable_raw = parseable.read_bytes()
        registry_entry["artifacts"].append({
            "role": "report",
            "path": parseable_relative,
            "size_bytes": len(parseable_raw),
            "sha256": hashlib.sha256(parseable_raw).hexdigest(),
        })
        with mock.patch.object(
            GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
            (deepcopy(registry_entry),),
        ):
            inventory, collisions = GENERATOR._evidence_identity_inventory(
                CORE, self.root,
            )
        registered_parseable = next(
            item for item in inventory if item["path"] == parseable_relative
        )
        self.assertEqual(collisions, [])
        self.assertTrue(registered_parseable["strict_json_readable"])
        self.assertEqual(
            registered_parseable["registry_index_instance_id"],
            "historical-abandoned-index-instance",
        )

        invalid_registries = []
        wrong_identity = deepcopy(registry_entry)
        wrong_identity["artifacts"][0]["sha256"] = "f" * 64
        invalid_registries.append(wrong_identity)
        wrong_status = deepcopy(registry_entry)
        wrong_status["generation_status"] = "COMMITTED_UNSELECTED"
        invalid_registries.append(wrong_status)
        current_generation = deepcopy(registry_entry)
        current_generation["generation_id"] = CORE.GENERATION_ID
        invalid_registries.append(current_generation)
        predecessor_generation = deepcopy(registry_entry)
        predecessor_generation["generation_id"] = (
            CORE.PREDECESSOR_INDEX_IDENTITY["generation_id"]
        )
        invalid_registries.append(predecessor_generation)
        current_index = deepcopy(registry_entry)
        current_index["index_instance_id"] = CORE.INDEX_INSTANCE_ID
        invalid_registries.append(current_index)
        outside_evidence = deepcopy(registry_entry)
        outside_evidence["artifacts"][0]["path"] = "out/partial.json"
        invalid_registries.append(outside_evidence)
        source_role = deepcopy(registry_entry)
        source_role["artifacts"][0]["path"] = self.doc_target
        invalid_registries.append(source_role)
        duplicate_role = deepcopy(registry_entry)
        duplicate_role["artifacts"][1]["role"] = "canonical"
        invalid_registries.append(duplicate_role)
        for invalid in invalid_registries:
            with self.subTest(registry=invalid):
                with mock.patch.object(
                    GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
                    (invalid,),
                ):
                    with self.assertRaises(GENERATOR.GenerationError):
                        GENERATOR._evidence_identity_inventory(CORE, self.root)
        self.assertEqual(GENERATOR.REGISTERED_NONSELECTABLE_GENERATIONS, ())

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

        def invoke(
            case_name, *, writer_fault=None, exact_anchor=False,
            resolver_raises=False, post_index_keyerror=False,
            drift_output=None, state_after_commit=None,
            workspace_root=None, registry=(), use_real_inventory=False,
        ):
            case_root = (
                Path(workspace_root)
                if workspace_root is not None
                else self.root / "commit_cases" / case_name
            )
            case_root.mkdir(parents=True, exist_ok=True)
            core_identity = _write(
                case_root, GENERATOR.CORE_RELATIVE_PATH,
                b"# exact fake authority core\n",
            )
            source_identity = _write(
                case_root, "source.py", b"SOURCE = True\n",
            )
            output_prefix = "evidence/commit_cases/" + case_name
            case_root.joinpath(*output_prefix.split("/")).mkdir(
                parents=True, exist_ok=True,
            )
            fake = SimpleNamespace(
                GENERATION_ID="fixture-generation-" + case_name,
                INDEX_INSTANCE_ID="fixture-index-" + case_name,
                CURRENT_EVIDENCE_ID="fixture-evidence-" + case_name,
                CANONICAL_ARTIFACT_ID="fixture-canonical-artifact-" + case_name,
                CANONICAL_ID="fixture-canonical-" + case_name,
                REPORT_ID="fixture-report-" + case_name,
                CANONICAL_RELATIVE_PATH=output_prefix + "/canonical.json",
                REPORT_RELATIVE_PATH=output_prefix + "/report.json",
                INDEX_RELATIVE_PATH=output_prefix + "/index.json",
                PREDECESSOR_INDEX_IDENTITY={
                    "path": "evidence/predecessor/index.json",
                    "index_instance_id": "successful-predecessor-index",
                    "generation_id": "successful-predecessor-generation",
                },
                PREDECESSOR_REPORT_IDENTITY={
                    "path": "evidence/predecessor/report.json",
                },
                PREDECESSOR_CANONICAL_IDENTITY={
                    "path": "evidence/predecessor/canonical.json",
                },
                REQUIRED_SOURCE_ROLE_DEFINITIONS=(
                    ("source", "workspace", "source.py"),
                ),
                EXECUTION_DEFINITIONS=(),
                PRODUCTION_CLI_EXPECTATIONS=(),
                ATOMIC_SUPPORTING_TEST_ID="fixture.atomic.test",
            )
            source_roles = [{"role": "source", **source_identity}]
            host_binding = {"tree_sha256": "a" * 64}
            overlay_binding = {"tree_sha256": "b" * 64}
            fake.collect_source_role_bindings = lambda unused_root: deepcopy(
                source_roles
            )
            fake.collect_host_perception_package_tree = (
                lambda unused_root: deepcopy(host_binding)
            )
            fake.collect_live_overlay_binding = (
                lambda unused_root: deepcopy(overlay_binding)
            )
            fake.source_artifact_identity = CORE.source_artifact_identity
            fake._read_regular_identity = CORE._read_regular_identity
            fake.build_canonical_payload = lambda unused_root, unused_roles: {
                "generation_id": fake.GENERATION_ID,
                "live_overlay_binding": deepcopy(overlay_binding),
                "formal_consumer": False,
                "delivery_ready": False,
            }
            fake.build_report_payload = (
                lambda unused_root, unused_canonical, unused_roles,
                unused_logical, unused_physical, unused_composites,
                unused_observations: {
                    "evidence_id": fake.CURRENT_EVIDENCE_ID,
                    "generation_id": fake.GENERATION_ID,
                    "formal_consumer": False,
                    "delivery_ready": False,
                }
            )

            def build_index(report_identity, canonical_identity, unused_roles):
                return {
                    "index_instance_id": fake.INDEX_INSTANCE_ID,
                    "generation_id": fake.GENERATION_ID,
                    "current_evidence_id": fake.CURRENT_EVIDENCE_ID,
                    "entries": [{
                        "evidence_id": fake.CURRENT_EVIDENCE_ID,
                        "is_current": True,
                        **dict(report_identity),
                    }],
                    "child_artifacts": [{
                        "artifact_id": fake.CANONICAL_ARTIFACT_ID,
                        "canonical_id": fake.CANONICAL_ID,
                        **dict(canonical_identity),
                    }],
                }
            fake.build_index_payload = build_index

            def validate_index(unused_root, unused_index):
                if drift_output is not None:
                    relative = (
                        fake.CANONICAL_RELATIVE_PATH
                        if drift_output == "canonical"
                        else fake.REPORT_RELATIVE_PATH
                    )
                    drift_path = case_root.joinpath(*relative.split("/"))
                    drift_path.write_bytes(drift_path.read_bytes() + b" ")
                return {"semantic_validated_pass": True, "failures": []}
            fake.validate_formal_admission_evidence_authority_v6 = validate_index

            def resolve(unused_root, unused_identity):
                if resolver_raises:
                    raise RuntimeError("resolver-fault")
                return {
                    "validated_pass": True,
                    "accepted_as_offline_release_selection_authority": True,
                    "failures": [],
                }
            fake.load_and_resolve_formal_admission_evidence_authority_v6 = resolve

            writer_calls = []
            role_by_path = {
                fake.CANONICAL_RELATIVE_PATH: "canonical",
                fake.REPORT_RELATIVE_PATH: "report",
                fake.INDEX_RELATIVE_PATH: "index",
            }

            def writer(output_path, payload, reported_path=None):
                role = role_by_path[reported_path]
                writer_calls.append(role)
                if writer_fault == role + "_before":
                    raise RuntimeError(role + "-before")
                if writer_fault == role + "_create_only":
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb"):
                        pass
                    raise RuntimeError(role + "-create-only")
                if writer_fault == role + "_partial":
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb") as stream:
                        stream.write(b"{")
                    raise RuntimeError(role + "-partial")
                if writer_fault == role + "_post_fsync":
                    raw = (
                        json.dumps(
                            payload, ensure_ascii=False, indent=2,
                            sort_keys=True, allow_nan=False,
                        ) + "\n"
                    ).encode("utf-8")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    raise RuntimeError(role + "-post-fsync-pre-reopen")
                if writer_fault == role + "_reopen":
                    original_read_bytes = Path.read_bytes
                    def fail_exact_reopen(read_path):
                        if read_path == output_path:
                            raise OSError(role + "-reopen")
                        return original_read_bytes(read_path)
                    with mock.patch.object(
                        Path, "read_bytes", new=fail_exact_reopen,
                    ):
                        return CORE.write_json_exclusive(
                            output_path, payload, reported_path,
                        )
                identity = CORE.write_json_exclusive(
                    output_path, payload, reported_path,
                )
                return identity
            fake.write_json_exclusive = writer

            def wrapper_status(unused_root, identity):
                index_path = case_root.joinpath(
                    *fake.INDEX_RELATIVE_PATH.split("/")
                )
                anchor = None
                if exact_anchor and index_path.exists():
                    anchor = CORE.source_artifact_identity(
                        case_root, "workspace", fake.INDEX_RELATIVE_PATH,
                    )
                    anchor = {
                        key: anchor[key]
                        for key in ("path", "size_bytes", "sha256")
                    }
                return {
                    "configured_core_anchor": dict(identity),
                    "matches_live_core": True,
                    "configured_production_index_anchor": anchor,
                }

            logical = [{}] if post_index_keyerror else [{"collected": 1}]
            original_generation_state = GENERATOR._current_generation_output_state
            state_mutated = {"done": False}
            def generation_state(core_arg, root_arg, identity_arg):
                index_path = root_arg.joinpath(
                    *core_arg.INDEX_RELATIVE_PATH.split("/")
                )
                if index_path.exists():
                    if state_after_commit == "raise":
                        raise RuntimeError("post-index-state-fault")
                    if (
                        state_after_commit == "truncate"
                        and not state_mutated["done"]
                    ):
                        state_mutated["done"] = True
                        index_path.write_bytes(b"{")
                return original_generation_state(
                    core_arg, root_arg, identity_arg,
                )

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_require_generation_context",
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_load_core",
                    return_value=(fake, core_identity),
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_wrapper_core_anchor_status",
                    side_effect=wrapper_status,
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "REGISTERED_NONSELECTABLE_GENERATIONS",
                    tuple(registry),
                ))
                if not use_real_inventory:
                    stack.enter_context(mock.patch.object(
                        GENERATOR, "_evidence_identity_inventory",
                        return_value=([], []),
                    ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_frozen_source_mismatches",
                    return_value=[],
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_run_execution_matrix",
                    return_value=(
                        logical,
                        [{"collected": 1, "passed": 1, "skipped": 0}],
                        [], {}, {},
                    ),
                ))
                stack.enter_context(mock.patch.object(
                    GENERATOR, "_production_observations",
                    return_value=[],
                ))
                if state_after_commit is not None:
                    stack.enter_context(mock.patch.object(
                        GENERATOR, "_current_generation_output_state",
                        side_effect=generation_state,
                    ))
                result = GENERATOR._generate(case_root)
            return result, writer_calls, fake, case_root

        fault_expectations = (
            ("canonical-before", "canonical_before", "FAILED_NO_ARTIFACTS"),
            ("canonical-create-only", "canonical_create_only", "ABANDONED_UNINDEXED"),
            ("canonical-partial", "canonical_partial", "ABANDONED_UNINDEXED"),
            ("canonical-post-fsync", "canonical_post_fsync", "ABANDONED_UNINDEXED"),
            ("canonical-reopen", "canonical_reopen", "ABANDONED_UNINDEXED"),
            ("report-before", "report_before", "ABANDONED_UNINDEXED"),
            ("report-create-only", "report_create_only", "ABANDONED_UNINDEXED"),
            ("report-partial", "report_partial", "ABANDONED_UNINDEXED"),
            ("report-post-fsync", "report_post_fsync", "ABANDONED_UNINDEXED"),
            ("report-reopen", "report_reopen", "ABANDONED_UNINDEXED"),
            ("index-before", "index_before", "ABANDONED_UNINDEXED"),
            ("index-create-only", "index_create_only", "ABANDONED_UNINDEXED"),
            ("index-partial", "index_partial", "ABANDONED_UNINDEXED"),
            ("index-post-fsync", "index_post_fsync", "COMMITTED_UNSELECTED"),
            ("index-reopen", "index_reopen", "COMMITTED_UNSELECTED"),
        )
        fault_results = {}
        for case_name, fault, expected_status in fault_expectations:
            with self.subTest(fault=fault):
                result, calls, fake, case_root = invoke(
                    case_name, writer_fault=fault,
                )
                fault_results[case_name] = (result, fake, case_root)
                self.assertEqual(result["generation_status"], expected_status)
                self.assertFalse(result["selected"])
                self.assertFalse(result["delivery_ready"])
                expected_committed = expected_status == "COMMITTED_UNSELECTED"
                expected_abandoned = expected_status == "ABANDONED_UNINDEXED"
                self.assertIs(result["index_committed"], expected_committed)
                self.assertIs(
                    result["same_generation_retry_forbidden"],
                    expected_committed or expected_abandoned,
                )
                self.assertIs(
                    result["requires_new_generation_id"], expected_abandoned,
                )
                self.assertIs(
                    result["selection_anchor_unset"], expected_committed,
                )
                self.assertGreaterEqual(len(calls), 1)
        self.assertIn(
            "generation_index_o_excl_commit_not_completed",
            fault_results["index-partial"][0]["failures"],
        )
        self.assertTrue(
            fault_results["index-post-fsync"][0]["index_committed"]
        )
        self.assertEqual(
            fault_results["index-post-fsync"][0]["commit_basis"],
            "EXACT_INDEX_BYTES",
        )

        for case_name, unused_fault, expected_status in fault_expectations:
            original_result, original_fake, original_root = fault_results[
                case_name
            ]
            role_paths = {
                "canonical": original_fake.CANONICAL_RELATIVE_PATH,
                "report": original_fake.REPORT_RELATIVE_PATH,
                "index": original_fake.INDEX_RELATIVE_PATH,
            }
            original_bytes = {
                relative: original_root.joinpath(
                    *relative.split("/")
                ).read_bytes()
                for relative in role_paths.values()
                if original_root.joinpath(*relative.split("/")).is_file()
            }
            if expected_status == "FAILED_NO_ARTIFACTS":
                self.assertEqual(original_bytes, {})
            else:
                retry, retry_calls, unused, unused = invoke(case_name)
                self.assertEqual(retry_calls, [])
                self.assertEqual(retry["generation_status"], expected_status)
                self.assertEqual(original_bytes, {
                    relative: original_root.joinpath(
                        *relative.split("/")
                    ).read_bytes()
                    for relative in original_bytes
                })

            registry = ()
            if expected_status == "ABANDONED_UNINDEXED":
                artifacts = []
                for role, relative in role_paths.items():
                    if relative not in original_bytes:
                        continue
                    identity = CORE.source_artifact_identity(
                        original_root, "workspace", relative,
                    )
                    artifacts.append({
                        "role": role,
                        **{
                            key: identity[key]
                            for key in ("path", "size_bytes", "sha256")
                        },
                    })
                registry = ({
                    "schema_version": (
                        "registered_nonselectable_generation/v1"
                    ),
                    "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
                    "generation_status": "ABANDONED_UNINDEXED",
                    "generation_id": original_fake.GENERATION_ID,
                    "index_instance_id": original_fake.INDEX_INSTANCE_ID,
                    "artifacts": artifacts,
                },)
            next_result, next_calls, next_fake, unused = invoke(
                "next-" + case_name,
                workspace_root=original_root,
                registry=registry,
                use_real_inventory=True,
            )
            self.assertEqual(next_calls, ["canonical", "report", "index"])
            self.assertEqual(
                next_result["generation_status"], "COMMITTED_UNSELECTED"
            )
            self.assertTrue(original_root.joinpath(
                *next_fake.INDEX_RELATIVE_PATH.split("/")
            ).is_file())
            self.assertEqual(original_bytes, {
                relative: original_root.joinpath(
                    *relative.split("/")
                ).read_bytes()
                for relative in original_bytes
            })
            if expected_status == "FAILED_NO_ARTIFACTS":
                self.assertTrue(all(
                    not original_root.joinpath(*relative.split("/")).exists()
                    for relative in role_paths.values()
                ))

        committed, committed_calls, committed_fake, committed_root = invoke(
            "committed-unselected",
        )
        self.assertEqual(committed_calls, ["canonical", "report", "index"])
        self.assertEqual(committed["generation_status"], "COMMITTED_UNSELECTED")
        self.assertTrue(committed["index_committed"])
        self.assertTrue(committed["selection_anchor_unset"])
        self.assertTrue(committed["independent_resolution_pending"])
        self.assertFalse(
            committed["accepted_as_offline_release_selection_authority"]
        )
        committed_retry, committed_retry_calls, unused, unused = invoke(
            "committed-unselected",
        )
        self.assertEqual(committed_retry_calls, [])
        self.assertEqual(
            committed_retry["generation_status"], "COMMITTED_UNSELECTED"
        )

        selected, selected_calls, unused, unused = invoke(
            "selected", exact_anchor=True,
        )
        self.assertEqual(selected_calls, ["canonical", "report", "index"])
        self.assertEqual(selected["generation_status"], "SELECTED_BLOCKED_OFFLINE")
        self.assertTrue(
            selected["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(selected["independent_resolution_pending"])
        self.assertFalse(selected["formal_consumer"])
        self.assertFalse(selected["delivery_ready"])

        resolver_result, unused, unused, unused = invoke(
            "resolver-exception", resolver_raises=True,
        )
        self.assertEqual(
            resolver_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_post_commit_candidate_resolver_exception",
            resolver_result["failures"],
        )
        post_commit_result, unused, unused, unused = invoke(
            "post-index-exception", post_index_keyerror=True,
        )
        self.assertEqual(
            post_commit_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_post_commit_candidate_validation_failed",
            post_commit_result["failures"],
        )
        for state_mode in ("truncate", "raise"):
            state_result, unused, unused, unused = invoke(
                "post-index-state-" + state_mode,
                state_after_commit=state_mode,
            )
            self.assertEqual(
                state_result["generation_status"], "COMMITTED_UNSELECTED"
            )
            self.assertTrue(state_result["index_committed"])
            self.assertTrue(state_result["selection_anchor_unset"])
            self.assertIn(
                "formal_authority_v6_production_anchor_not_configured",
                state_result["failures"],
            )
            self.assertIn(
                "generation_post_commit_candidate_validation_failed",
                state_result["failures"],
            )

        for output_role in ("canonical", "report"):
            drift_result, unused, drift_fake, drift_root = invoke(
                "pre-index-drift-" + output_role,
                drift_output=output_role,
            )
            self.assertEqual(
                drift_result["generation_status"], "ABANDONED_UNINDEXED"
            )
            self.assertIn(
                "generation_exception:GenerationError:"
                "generation_output_identity_drift_before_index_commit:"
                + output_role,
                drift_result["failures"],
            )
            self.assertFalse(drift_root.joinpath(
                *drift_fake.INDEX_RELATIVE_PATH.split("/")
            ).exists())

        committed_report = committed_root.joinpath(
            *committed_fake.REPORT_RELATIVE_PATH.split("/")
        )
        committed_report.unlink()
        missing_child, missing_calls, unused, unused = invoke(
            "committed-unselected",
        )
        self.assertEqual(missing_calls, [])
        self.assertEqual(
            missing_child["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertIn(
            "generation_current_output_missing:report",
            missing_child["failures"],
        )

        abandoned_result, unused, abandoned_fake, abandoned_root = invoke(
            "plan-index-partial", writer_fault="index_partial",
        )
        self.assertEqual(
            abandoned_result["generation_status"], "ABANDONED_UNINDEXED"
        )

        abandoned_core_identity = CORE.source_artifact_identity(
            abandoned_root, "workspace", GENERATOR.CORE_RELATIVE_PATH,
        )
        abandoned_wrapper_status = {
            "configured_core_anchor": dict(abandoned_core_identity),
            "matches_live_core": True,
            "configured_production_index_anchor": None,
        }
        with mock.patch.object(
            GENERATOR, "_load_core",
            return_value=(abandoned_fake, abandoned_core_identity),
        ), mock.patch.object(
            GENERATOR, "_wrapper_core_anchor_status",
            return_value=abandoned_wrapper_status,
        ), mock.patch.object(
            GENERATOR, "_evidence_identity_inventory",
            side_effect=AssertionError("inventory must be skipped"),
        ):
            abandoned_plan = GENERATOR._plan(abandoned_root)
            self.assertEqual(
                abandoned_plan["generation_status"], "ABANDONED_UNINDEXED"
            )
            self.assertFalse(abandoned_plan["ready_to_attempt_generation"])
            self.assertTrue(
                abandoned_plan[
                    "evidence_inventory_skipped_for_existing_generation"
                ]
            )
            output = io.StringIO()
            with mock.patch.object(
                GENERATOR, "_workspace_root", return_value=abandoned_root,
            ), mock.patch.object(sys, "stdout", output):
                self.assertEqual(GENERATOR.main(["--plan"]), 3)
            marker_payload = json.loads(
                output.getvalue().split(GENERATOR.PLAN_MARKER, 1)[1]
            )
            self.assertEqual(
                marker_payload["generation_status"], "ABANDONED_UNINDEXED"
            )

        malformed_raws = {
            "duplicate": b'{"generation_id":"a","generation_id":"b"}',
            "nan": b'{"value":NaN}',
        }
        malformed_cases = {}
        for malformed_name, malformed_raw in malformed_raws.items():
            malformed_result, unused, malformed_fake, malformed_root = invoke(
                "malformed-" + malformed_name,
                writer_fault="index_partial",
            )
            malformed_index = malformed_root.joinpath(
                *malformed_fake.INDEX_RELATIVE_PATH.split("/")
            )
            malformed_index.write_bytes(malformed_raw)
            retry, calls, unused, unused = invoke(
                "malformed-" + malformed_name,
            )
            self.assertEqual(calls, [])
            self.assertEqual(retry["generation_status"], "ABANDONED_UNINDEXED")
            self.assertEqual(malformed_index.read_bytes(), malformed_raw)
            malformed_cases[malformed_name] = (
                malformed_fake, malformed_root, malformed_raw,
            )

        wrong_type_result, unused, wrong_type_fake, wrong_type_root = invoke(
            "malformed-child-type", writer_fault="index_partial",
        )
        wrong_type_report = CORE.source_artifact_identity(
            wrong_type_root, "workspace", wrong_type_fake.REPORT_RELATIVE_PATH,
        )
        wrong_type_index = wrong_type_root.joinpath(
            *wrong_type_fake.INDEX_RELATIVE_PATH.split("/")
        )
        wrong_type_index.write_bytes(_json_bytes({
            "index_instance_id": wrong_type_fake.INDEX_INSTANCE_ID,
            "generation_id": wrong_type_fake.GENERATION_ID,
            "current_evidence_id": wrong_type_fake.CURRENT_EVIDENCE_ID,
            "entries": [{
                "evidence_id": wrong_type_fake.CURRENT_EVIDENCE_ID,
                "is_current": True,
                **{
                    key: wrong_type_report[key]
                    for key in ("path", "size_bytes", "sha256")
                },
            }],
            "child_artifacts": [0],
        }))
        wrong_type_retry, wrong_type_calls, unused, unused = invoke(
            "malformed-child-type",
        )
        self.assertEqual(wrong_type_calls, [])
        self.assertEqual(
            wrong_type_retry["generation_status"], "ABANDONED_UNINDEXED"
        )

        # Exercise the registry's GenerationError path, not only an ordinary
        # JSONDecodeError, before a distinct generation is allowed to proceed.
        abandoned_fake, abandoned_root, unused_raw = malformed_cases[
            "duplicate"
        ]
        registered_artifacts = []
        for role, relative in (
            ("canonical", abandoned_fake.CANONICAL_RELATIVE_PATH),
            ("report", abandoned_fake.REPORT_RELATIVE_PATH),
            ("index", abandoned_fake.INDEX_RELATIVE_PATH),
        ):
            identity = CORE.source_artifact_identity(
                abandoned_root, "workspace", relative,
            )
            registered_artifacts.append({
                "role": role,
                **{
                    key: identity[key]
                    for key in ("path", "size_bytes", "sha256")
                },
            })
        registry = ({
            "schema_version": "registered_nonselectable_generation/v1",
            "registry_status": "REGISTERED_NONSELECTABLE_GENERATION",
            "generation_status": "ABANDONED_UNINDEXED",
            "generation_id": abandoned_fake.GENERATION_ID,
            "index_instance_id": abandoned_fake.INDEX_INSTANCE_ID,
            "artifacts": registered_artifacts,
        },)
        registered_bytes_before = {
            item["path"]: abandoned_root.joinpath(
                *item["path"].split("/")
            ).read_bytes()
            for item in registered_artifacts
        }
        next_result, next_calls, next_fake, unused = invoke(
            "next-generation",
            workspace_root=abandoned_root,
            registry=registry,
            use_real_inventory=True,
        )
        self.assertEqual(next_calls, ["canonical", "report", "index"])
        self.assertEqual(
            next_result["generation_status"], "COMMITTED_UNSELECTED"
        )
        self.assertTrue(abandoned_root.joinpath(
            *next_fake.INDEX_RELATIVE_PATH.split("/")
        ).is_file())
        self.assertEqual(registered_bytes_before, {
            item["path"]: abandoned_root.joinpath(
                *item["path"].split("/")
            ).read_bytes()
            for item in registered_artifacts
        })

        for status, expected_exit in (
            ("FAILED_NO_ARTIFACTS", 4),
            ("ABANDONED_UNINDEXED", 4),
            ("COMMITTED_UNSELECTED", 0),
            ("SELECTED_BLOCKED_OFFLINE", 0),
        ):
            with mock.patch.object(GENERATOR, "_workspace_root", return_value=self.root), \
                    mock.patch.object(
                        GENERATOR, "_generate",
                        return_value={"generation_status": status},
                    ), mock.patch.object(sys, "stdout", io.StringIO()):
                self.assertEqual(GENERATOR.main(["--generate"]), expected_exit)
        with mock.patch.object(GENERATOR, "_workspace_root", return_value=self.root), \
                mock.patch.object(
                    GENERATOR, "_generate",
                    side_effect=RuntimeError("outer-fault"),
                ), mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(GENERATOR.main(["--generate"]), 2)

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
            ("semantic_evidence_producer_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_semantic_evidence_producer.py"),
            ("field_readiness_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness.py"),
            ("field_readiness_exact_cli_test", "workspace", "src/limo_cleanup_perception/test/test_ros1_noetic_field_readiness_exact_cli.py"),
            ("perception_package_setup", "workspace", "src/limo_cleanup_perception/setup.py"),
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
            "formal_authority_v6_host_package_tree_invalid", failures,
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
            "formal_authority_v6_host_package_tree_invalid", failures,
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
            "formal_authority_v6_host_package_tree_invalid", failures,
        )
        missing_cache.write_bytes(b"fixture pyc bytes\n")

        cache_subdirectory = self.root / package_root / "__pycache__" / "nested"
        cache_subdirectory.mkdir()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v6_host_package_tree_invalid", failures,
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
                "formal_authority_v6_host_package_tree_invalid", failures,
            )
            link.unlink()

        missing = self.root / package_root / "b.py"
        missing.unlink()
        failures, unused = CORE._validate_source_roles(
            self.root, roles, policy,
        )
        self.assertIn(
            "formal_authority_v6_host_package_tree_invalid", failures,
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
        # The isolated child deliberately cannot read workspace bytecode.
        # The generation parent owns the live host-tree identity read and
        # recomputes it before and after the execution matrix and again before
        # the index commit point.  Keep this child assertion structural so no
        # ordinary pyc path exception is introduced into the source-only guard.
        policy = CORE.PRODUCTION_POLICY
        self.assertEqual(
            policy.host_perception_package_root,
            CORE.HOST_PERCEPTION_PACKAGE_ROOT,
        )
        self.assertEqual(
            policy.host_perception_package_files,
            CORE.HOST_PERCEPTION_PACKAGE_FILES,
        )
        self.assertEqual(
            policy.host_perception_cache_files,
            CORE.HOST_PERCEPTION_CACHE_FILES,
        )
        source_role_paths = {
            (root_role, path)
            for unused_role, root_role, path
            in policy.source_role_definitions
        }
        self.assertIn(("workspace", init_path), source_role_paths)
        self.assertEqual(
            {
                path for root_role, path in source_role_paths
                if (
                    root_role == "workspace"
                    and path.startswith(
                        CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/"
                    )
                )
            },
            {
                CORE.HOST_PERCEPTION_PACKAGE_ROOT + "/__pycache__/" + name
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
            "formal_authority_v6_source_role_size_invalid", failures,
        )

    def test_production_suite_inventory_is_mechanical_and_contains_new_suites(self):
        inventory = CORE.suite_inventory(ROOT)
        by_id = {item["suite_id"]: item for item in inventory}
        for suite_id in (
            "camera_runtime_import_probe", "camera_runtime_install_admission",
            "camera_only_atomic_launcher", "machine_contract_doc_demotion",
            "camera_only_operator_docs", "runtime_source_contract",
            "dabai_runtime_contract", "legacy_operational_scripts",
            "perception_release_artifacts", "field_readiness",
            "field_readiness_exact_cli", "semantic_evidence_producer",
            "successor_authority_validator",
        ):
            self.assertIn(suite_id, by_id)
            self.assertGreater(by_id[suite_id]["logical_count"], 0)
        self.assertIn(
            CORE.ATOMIC_SUPPORTING_TEST_ID,
            by_id["camera_only_atomic_launcher"]["expected_test_ids"],
        )
        semantic_records = [
            item for item in CORE.EXECUTION_DEFINITIONS
            if item["suite_id"] == "semantic_evidence_producer"
        ]
        self.assertEqual(
            {item["interpreter_role"] for item in semantic_records},
            {"system_python3_entry", "system_python314_target"},
        )
        self.assertEqual(len(CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS), 101)
        self.assertIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            CORE.EXTERNAL_TRUST_ROOT_EXCLUSIONS,
        )
        self.assertNotIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            {path for unused, unused_root, path
             in CORE.REQUIRED_SOURCE_ROLE_DEFINITIONS},
        )

        definitions = {
            item["record_id"]: item for item in CORE.EXECUTION_DEFINITIONS
        }
        wrapper_identity = CORE.artifact_identity(
            ROOT, CORE.GENERATION_WRAPPER_SOURCE_PATH,
        )
        target_observation = {
            "path": CORE.GENERATION_WRAPPER_SOURCE_PATH,
            "parent_before": deepcopy(wrapper_identity),
            "child_read": deepcopy(wrapper_identity),
            "parent_after": deepcopy(wrapper_identity),
        }
        target_marker = {
            "workspace_source_reads": [deepcopy(wrapper_identity)],
        }
        self.assertEqual([], CORE._external_wrapper_observation_failures(
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, target_marker,
            target_observation, definitions,
        ))
        other_record_id = "probe_wsl_python314"
        other_observation = {
            "path": CORE.GENERATION_WRAPPER_SOURCE_PATH,
            "parent_before": deepcopy(wrapper_identity),
            "child_read": None,
            "parent_after": deepcopy(wrapper_identity),
        }
        self.assertEqual([], CORE._external_wrapper_observation_failures(
            other_record_id, {"workspace_source_reads": []},
            other_observation, definitions,
        ))

        wrong_identity = deepcopy(wrapper_identity)
        wrong_identity["sha256"] = "f" * 64
        core_scope_cases = []
        missing = deepcopy(target_marker)
        missing["workspace_source_reads"] = []
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, missing,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        wrong = deepcopy(target_marker)
        wrong["workspace_source_reads"] = [deepcopy(wrong_identity)]
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, wrong,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        duplicate = deepcopy(target_marker)
        duplicate["workspace_source_reads"].append(
            deepcopy(wrapper_identity))
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID, duplicate,
            deepcopy(target_observation), "marker_read_scope_invalid",
        ))
        wrong_record_observation = deepcopy(other_observation)
        wrong_record_observation["child_read"] = deepcopy(wrapper_identity)
        core_scope_cases.append((
            other_record_id, deepcopy(target_marker),
            wrong_record_observation, "child_read_scope_invalid",
        ))
        parent_drift = deepcopy(target_observation)
        parent_drift["parent_after"] = deepcopy(wrong_identity)
        core_scope_cases.append((
            CORE.GENERATION_WRAPPER_READ_RECORD_ID,
            deepcopy(target_marker), parent_drift, "parent_identity_drift",
        ))
        for record_id, marker, observation, expected_code in core_scope_cases:
            failures = CORE._external_wrapper_observation_failures(
                record_id, marker, observation, definitions,
            )
            self.assertTrue(any(
                expected_code in failure for failure in failures
            ), (record_id, expected_code, failures))

        wrong_definitions = deepcopy(definitions)
        wrong_definitions[CORE.GENERATION_WRAPPER_READ_RECORD_ID] = {
            **wrong_definitions[CORE.GENERATION_WRAPPER_READ_RECORD_ID],
            "suite_id": "wrong_suite",
        }
        self.assertTrue(any(
            "record_definition_invalid" in failure
            for failure in CORE._external_wrapper_observation_failures(
                CORE.GENERATION_WRAPPER_READ_RECORD_ID, target_marker,
                target_observation, wrong_definitions,
            )
        ))

        observation_by_id = {
            record_id: {
                "external_wrapper_observation": deepcopy(
                    target_observation
                    if record_id == CORE.GENERATION_WRAPPER_READ_RECORD_ID
                    else other_observation
                ),
            }
            for record_id in definitions
        }
        self.assertEqual([], CORE._external_wrapper_observation_set_failures(
            observation_by_id, definitions,
        ))
        split = deepcopy(observation_by_id)
        split[other_record_id]["external_wrapper_observation"][
            "parent_after"
        ] = deepcopy(wrong_identity)
        self.assertIn(
            "formal_authority_v6_external_wrapper_parent_identity_split",
            CORE._external_wrapper_observation_set_failures(
                split, definitions,
            ),
        )
        missing_observation = deepcopy(observation_by_id)
        missing_observation[other_record_id][
            "external_wrapper_observation"
        ] = None
        self.assertIn(
            "formal_authority_v6_external_wrapper_observation_set_invalid",
            CORE._external_wrapper_observation_set_failures(
                missing_observation, definitions,
            ),
        )

        stable_signature = [{"component": "wrapper", "mtime_ns": 1}]
        target_definition = definitions[
            CORE.GENERATION_WRAPPER_READ_RECORD_ID
        ]
        generated = GENERATOR._external_wrapper_observation(
            CORE, target_definition, target_marker,
            wrapper_identity, stable_signature,
            wrapper_identity, stable_signature,
        )
        self.assertEqual(generated, target_observation)
        generated_other = GENERATOR._external_wrapper_observation(
            CORE, definitions[other_record_id],
            {"workspace_source_reads": []},
            wrapper_identity, stable_signature,
            wrapper_identity, stable_signature,
        )
        self.assertEqual(generated_other, other_observation)
        for marker in (missing, wrong, duplicate):
            with self.assertRaisesRegex(
                    GENERATOR.GenerationError,
                    "child_external_wrapper_read_scope_invalid"):
                GENERATOR._external_wrapper_observation(
                    CORE, target_definition, marker,
                    wrapper_identity, stable_signature,
                    wrapper_identity, stable_signature,
                )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_read_scope_invalid"):
            GENERATOR._external_wrapper_observation(
                CORE, definitions[other_record_id], target_marker,
                wrapper_identity, stable_signature,
                wrapper_identity, stable_signature,
            )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_parent_identity_drift"):
            GENERATOR._external_wrapper_observation(
                CORE, target_definition, target_marker,
                wrapper_identity, stable_signature,
                wrong_identity, stable_signature,
            )
        with self.assertRaisesRegex(
                GENERATOR.GenerationError,
                "child_external_wrapper_runtime_drift"):
            GENERATOR._external_wrapper_observation(
                CORE, target_definition, target_marker,
                wrapper_identity, stable_signature,
                wrapper_identity,
                [{"component": "wrapper", "mtime_ns": 2}],
            )

    def test_workspace_timestamp_pyc_is_blocked_and_loader_report_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            package = workspace / "poison_package"
            package.mkdir()
            package_source = package / "__init__.py"
            malicious = b"VALUE = 'PYC'\n"
            benign = b"VALUE = 'SRC'\n"
            self.assertEqual(len(malicious), len(benign))
            stamp = 1_700_000_000
            package_source.write_bytes(malicious)
            os.utime(package_source, (stamp, stamp))
            pyc_path = Path(py_compile.compile(
                str(package_source), doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            ))
            package_source.write_bytes(benign)
            os.utime(package_source, (stamp, stamp))
            relative_pyc = pyc_path.relative_to(workspace).as_posix()
            (workspace / "direct.pyc").write_bytes(b"DIRECT_PYC_BYTES")

            child_environment = (
                GENERATOR._outer_windows_environment()
                if os.name == "nt" else dict(CORE.CHILD_ENVIRONMENT)
            )
            control = subprocess.run(
                [
                    sys.executable, "-I", "-S", "-B", "-c",
                    "import sys;sys.path.insert(0,{!r});"
                    "import poison_package;print(poison_package.VALUE)".format(
                        str(workspace)
                    ),
                ],
                cwd=str(workspace), env=child_environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False, timeout=30,
                close_fds=True,
            )
            self.assertEqual(0, control.returncode, control.stderr)
            self.assertEqual([b"PYC"], control.stdout.splitlines())

            runner_cases = (
                (
                    CORE.UNITTEST_RUNNER, False, "sample_unittest.py",
                     "sample_unittest.py::LoaderCase.test_source_only",
                     b"from pathlib import Path\nimport unittest\nimport poison_package\n"
                     b"class LoaderCase(unittest.TestCase):\n"
                     b"    def test_source_only(self):\n"
                     b"        with self.assertRaises(PermissionError):\n"
                     b"            Path('direct.pyc').read_bytes()\n"
                     b"        self.assertEqual('SRC', poison_package.VALUE)\n",
                    CORE.UNITTEST_MARKER,
                ),
                (
                    CORE.PYTEST_RUNNER, True, "sample_pytest.py",
                    "sample_pytest.py::test_source_only",
                     b"from pathlib import Path\nimport poison_package\n"
                     b"def test_source_only():\n"
                     b"    try:\n"
                     b"        Path('direct.pyc').read_bytes()\n"
                     b"    except PermissionError:\n"
                     b"        pass\n"
                     b"    else:\n"
                     b"        raise AssertionError('workspace pyc read was not blocked')\n"
                     b"    assert poison_package.VALUE == 'SRC'\n",
                    CORE.PYTEST_MARKER,
                ),
            )
            for runner_relative, pytest_style, target_name, test_id, raw, marker_prefix in runner_cases:
                (workspace / target_name).write_bytes(raw)
                argv = [
                    sys.executable, "-I", "-S", "-B",
                    str(ROOT.joinpath(*runner_relative.split("/"))),
                ]
                if pytest_style:
                    argv.append("--single-file")
                argv.extend((
                    "--workspace", str(workspace),
                    "--target", target_name,
                    "--import-root", ".",
                    "--expected-id", test_id,
                ))
                completed = subprocess.run(
                    argv, cwd=str(workspace), env=child_environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False, timeout=30,
                    close_fds=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                lines = completed.stdout.splitlines()
                self.assertEqual(1, len(lines), completed.stdout)
                self.assertTrue(lines[0].startswith(marker_prefix.encode("ascii")))
                marker = json.loads(lines[0][len(marker_prefix):])
                self.assertEqual(CORE.WORKSPACE_BYTECODE_POLICY,
                                 marker["workspace_bytecode_policy"])
                self.assertEqual(0, marker["workspace_pyc_bytes_read"])
                self.assertTrue(marker["workspace_loader_guard_restored"])
                self.assertTrue(marker["workspace_pyc_audit_hook_active"])
                self.assertEqual(
                    "WORKSPACE_PYC_SINGLE_LINK_INODE_V1",
                    marker["workspace_pyc_inode_policy"],
                )
                self.assertGreaterEqual(marker["workspace_pyc_inventory_count"], 2)
                self.assertTrue(marker["workspace_pyc_inventory_stable"])
                self.assertIn(relative_pyc,
                              marker["workspace_pyc_attempts_blocked"])
                self.assertIn("direct.pyc",
                              marker["workspace_pyc_attempts_blocked"])
                reads = {
                    item["path"]: item
                    for item in marker["workspace_source_reads"]
                }
                self.assertEqual(
                    hashlib.sha256(benign).hexdigest(),
                    reads["poison_package/__init__.py"]["sha256"],
                )

        def uppercase_blocked_path(report):
            record = report["test_matrix"]["physical_execution_records"][0]
            record["marker_payload"]["workspace_pyc_attempts_blocked"] = [
                "__PYCACHE__/UPPER.PYC",
            ]
            record["marker_payload_sha256"] = _sha(record["marker_payload"])

        self._replace_report(uppercase_blocked_path)
        uppercase_result = self._validate()
        self.assertTrue(
            uppercase_result["semantic_validated_pass"],
            uppercase_result["failures"],
        )
        self.tearDown()
        self.setUp()

        mutation_cases = (
            ("missing_policy", "policy_invalid"),
            ("pyc_bytes", "pyc_bytes_read_nonzero"),
            ("guard", "guard_not_restored"),
            ("audit_hook", "pyc_audit_hook_not_active"),
            ("inode_policy", "pyc_inode_policy_invalid"),
            ("inventory_count", "pyc_inventory_count_invalid"),
            ("inventory_stable", "pyc_inventory_not_stable"),
            ("unbound", "source_read_unbound"),
            ("blocked_path", "blocked_path_invalid"),
            ("blocked_duplicate", "blocked_paths_order_or_duplicate_invalid"),
            ("source_schema", "source_read_schema_invalid"),
            ("source_duplicate", "source_read_order_or_duplicate_invalid"),
            ("target_missing", "target_source_read_missing"),
            ("identity_mismatch", "source_read_identity_mismatch"),
        )
        for case, expected_code in mutation_cases:
            def mutate(report, case=case):
                record = report["test_matrix"]["physical_execution_records"][0]
                marker = record["marker_payload"]
                if case == "missing_policy":
                    marker.pop("workspace_bytecode_policy")
                elif case == "pyc_bytes":
                    marker["workspace_pyc_bytes_read"] = 1
                elif case == "guard":
                    marker["workspace_loader_guard_restored"] = False
                elif case == "audit_hook":
                    marker["workspace_pyc_audit_hook_active"] = False
                elif case == "inode_policy":
                    marker["workspace_pyc_inode_policy"] = "UNTRUSTED"
                elif case == "inventory_count":
                    marker["workspace_pyc_inventory_count"] = -1
                elif case == "inventory_stable":
                    marker["workspace_pyc_inventory_stable"] = False
                elif case == "unbound":
                    marker["workspace_source_reads"].append({
                        "path": "unbound.py", "size_bytes": 1,
                        "sha256": "f" * 64,
                    })
                    marker["workspace_source_reads"].sort(
                        key=lambda item: item["path"])
                elif case == "blocked_path":
                    marker["workspace_pyc_attempts_blocked"] = ["not_bytecode.py"]
                elif case == "blocked_duplicate":
                    marker["workspace_pyc_attempts_blocked"] = [
                        "__pycache__/x.pyc", "__pycache__/x.pyc",
                    ]
                elif case == "source_schema":
                    marker["workspace_source_reads"][0]["extra"] = True
                elif case == "source_duplicate":
                    marker["workspace_source_reads"].append(
                        deepcopy(marker["workspace_source_reads"][0]))
                elif case == "target_missing":
                    marker["workspace_source_reads"] = []
                else:
                    marker["workspace_source_reads"][0]["sha256"] = "f" * 64
                record["marker_payload_sha256"] = _sha(marker)
            self._replace_report(mutate)
            result = self._validate()
            self.assertTrue(any(
                expected_code in failure for failure in result["failures"]
            ), (case, result["failures"]))
            self.tearDown()
            self.setUp()

        from audit_tools import run_pytest_style_tests as pytest_runner
        from audit_tools import run_unittest_file_tests as unittest_runner

        hardlink_target = self.root / "hardlink-target.pyc"
        hardlink_target.write_bytes(b"HARDLINK_PYC")
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside_directory:
            outside_hardlink = Path(outside_directory) / "outside-hardlink"
            try:
                os.link(hardlink_target, outside_hardlink)
            except OSError:
                outside_hardlink = None
            if outside_hardlink is not None:
                guard_factories = (
                    lambda: unittest_runner._WorkspaceLoaderGuard(
                        self.root, {}),
                    lambda: pytest_runner.WorkspaceLoaderGuard(self.root),
                )
                for guard_factory in guard_factories:
                    candidate_guard = guard_factory()
                    with self.assertRaisesRegex(
                            ValueError, "workspace_bytecode_hardlink_rejected"):
                        if hasattr(candidate_guard, "__enter__"):
                            with candidate_guard:
                                pass
                        else:
                            candidate_guard.install()
                outside_hardlink.unlink()
        hardlink_target.unlink()

        loop_a = self.root / "loop-a.pyc"
        loop_b = self.root / "loop-b.pyc"
        loop_created = False
        try:
            loop_a.symlink_to(loop_b)
            loop_b.symlink_to(loop_a)
            loop_created = True
        except OSError:
            for path in (loop_a, loop_b):
                try:
                    path.unlink()
                except OSError:
                    pass
        if loop_created:
            with self.assertRaisesRegex(
                    ValueError, "workspace_bytecode_file_linklike"):
                with unittest_runner._WorkspaceLoaderGuard(self.root, {}):
                    pass
            loop_a.unlink()
            loop_b.unlink()

        original_loader = unittest_runner.importlib.machinery.SourceFileLoader

        class ReplacementSourceFileLoader:
            pass

        alias_target = self.root / "alias-target.pyc"
        alias_target.write_bytes(b"ALIAS_TARGET_PYC")
        outside_alias_directory = tempfile.TemporaryDirectory(
            dir=self.root.parent)
        outside_alias = Path(outside_alias_directory.name) / "alias-without-pyc-suffix"
        try:
            outside_alias.symlink_to(alias_target)
        except OSError:
            outside_alias = None
        guard_report = {}
        guard = unittest_runner._WorkspaceLoaderGuard(self.root, guard_report)
        with self.assertRaisesRegex(
                ValueError, "workspace_loader_guard_replaced_during_execution"):
            with guard:
                with self.assertRaises(PermissionError):
                    alias_target.read_bytes()
                if outside_alias is not None:
                    with self.assertRaises(PermissionError):
                        outside_alias.read_bytes()
                unittest_runner.importlib.machinery.SourceFileLoader = (
                    ReplacementSourceFileLoader)
        outside_alias_directory.cleanup()
        self.assertIs(
            original_loader,
            unittest_runner.importlib.machinery.SourceFileLoader,
        )
        self.assertTrue(guard_report["workspace_loader_guard_restored"])
        self.assertTrue(guard_report["workspace_pyc_audit_hook_active"])
        self.assertTrue(guard_report["workspace_pyc_inventory_stable"])
        self.assertIn(
            "alias-target.pyc",
            guard_report["workspace_pyc_attempts_blocked"],
        )

        pytest_guard = pytest_runner.WorkspaceLoaderGuard(self.root)
        original_pytest_loader = (
            pytest_runner.importlib.machinery.SourceFileLoader)
        pytest_guard.install()
        try:
            pytest_runner.importlib.machinery.SourceFileLoader = (
                ReplacementSourceFileLoader)
            self.assertFalse(pytest_guard._guard_is_installed())
        finally:
            pytest_guard.restore()
        self.assertIs(
            original_pytest_loader,
            pytest_runner.importlib.machinery.SourceFileLoader,
        )
        self.assertTrue(pytest_guard.tampered)
        self.assertTrue(pytest_guard.restored)

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
                "formal_authority_v6_production_anchor_not_configured",
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
        wrapper_fixture = self.root.joinpath(
            *CORE.GENERATION_WRAPPER_SOURCE_PATH.split("/")
        )
        wrapper_fixture.write_bytes(b"PRODUCTION_INDEX_TRUST_ANCHOR = None\n")
        before_anchor_bytes = self._validate()
        self.assertTrue(
            before_anchor_bytes["semantic_validated_pass"],
            before_anchor_bytes["failures"],
        )
        wrapper_fixture.write_bytes(
            b"PRODUCTION_INDEX_TRUST_ANCHOR = {'sha256': 'frozen'}\n"
        )
        after_anchor_bytes = self._validate()
        self.assertTrue(
            after_anchor_bytes["semantic_validated_pass"],
            after_anchor_bytes["failures"],
        )
        self.assertNotIn(
            CORE.GENERATION_WRAPPER_SOURCE_PATH,
            {item["path"] for item in self.source_roles},
        )
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

    def test_wrapper_core_source_anchor_is_exact_and_fails_closed_on_drift(self):
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
        self.assertIsNotNone(core)
        self.assertEqual(identity, expected)
        self.assertEqual(failures, [])

        original_anchor = WRAPPER.CORE_SOURCE_TRUST_ANCHOR
        try:
            cases = (
                (None, "formal_authority_v6_core_source_anchor_not_configured"),
                ({
                    "path": "audit_tools/formal_admission_evidence_authority_v5_core.py",
                    "size_bytes": expected["size_bytes"],
                    "sha256": expected["sha256"],
                }, "formal_authority_v6_core_source_anchor_path_mismatch"),
                ({
                    "path": expected["path"],
                    "size_bytes": expected["size_bytes"],
                    "sha256": "0" * 64,
                }, "formal_authority_v6_core_source_sha256_mismatch"),
                ({
                    "path": expected["path"],
                    "size_bytes": expected["size_bytes"] - 1,
                    "sha256": expected["sha256"],
                }, "formal_authority_v6_core_source_size_bytes_mismatch"),
            )
            for anchor, code in cases:
                with self.subTest(code=code):
                    WRAPPER.CORE_SOURCE_TRUST_ANCHOR = anchor
                    rejected, observed, rejected_failures = (
                        WRAPPER._load_exact_core(ROOT))
                    self.assertIsNone(rejected)
                    if anchor is None or code.endswith("path_mismatch"):
                        self.assertEqual(observed, {})
                    else:
                        self.assertEqual(observed, expected)
                    self.assertEqual(rejected_failures, [code])

            with tempfile.TemporaryDirectory() as directory:
                copy_root = Path(directory)
                copy_path = copy_root / WRAPPER.CORE_SOURCE_RELATIVE_PATH
                copy_path.parent.mkdir(parents=True)
                copy_path.write_bytes(raw + b"\n# source drift\n")
                WRAPPER.CORE_SOURCE_TRUST_ANCHOR = expected
                rejected, observed, rejected_failures = (
                    WRAPPER._load_exact_core(copy_root))
                self.assertIsNone(rejected)
                self.assertEqual(observed["path"], expected["path"])
                self.assertIn(
                    "formal_authority_v6_core_source_size_bytes_mismatch",
                    rejected_failures,
                )
                self.assertIn(
                    "formal_authority_v6_core_source_sha256_mismatch",
                    rejected_failures,
                )
        finally:
            WRAPPER.CORE_SOURCE_TRUST_ANCHOR = original_anchor

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
        # The frozen v5 production anchor is intentionally Windows-only in the
        # predecessor wrapper.  Supply that same exact external anchor here so
        # this stale-live-source assertion exercises the old selected payload
        # on every host instead of stopping at the POSIX anchor-unbound guard.
        result = OLD_WRAPPER.load_and_resolve_successor_authority(
            OLD_WRAPPER._WINDOWS_PRODUCTION_INDEX_TRUST_ANCHOR,
            ROOT,
        )
        self.assertFalse(result["validated_pass"])
        self.assertFalse(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            item.startswith("formal_authority_v5_source_role_identity_mismatch:")
            or item.startswith("formal_authority_v5_frozen_source_identity_mismatch:")
            for item in result["failures"]
        ), result["failures"])

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
