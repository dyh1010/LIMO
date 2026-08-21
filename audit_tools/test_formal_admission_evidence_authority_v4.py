"""Fail-closed tests for the camera-runtime BLOCKED_OFFLINE authority."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import types
import unittest

from audit_tools import formal_admission_evidence_authority_v3 as OLD_AUTHORITY
from audit_tools import formal_admission_evidence_authority_v4 as PRODUCTION
from audit_tools import formal_admission_evidence_authority_v4_core as CORE


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value):
    raw = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _child_file_identity(identity, absolute_path):
    return {
        "path": absolute_path,
        "size_bytes": identity["size_bytes"],
        "sha256": identity["sha256"],
        "regular_file": True,
        "is_symlink": False,
    }


def _child_executable(interpreter):
    chain = [{
        "path": item["path"],
        "link_target": item["link_text"],
        "next_path": item["next_path"],
    } for item in interpreter["entry_link_chain"]]
    target = _child_file_identity(
        interpreter["resolved_target"],
        interpreter["resolved_target"]["path"],
    )
    value = {
        "entry_path": interpreter["entry_path"],
        "entry_is_symlink": interpreter["entry_is_symlink"],
        "entry_lstat_size_bytes": (
            10 if interpreter["entry_is_symlink"]
            else interpreter["resolved_target"]["size_bytes"]
        ),
        "entry_link_chain": chain,
        "resolved_target": target,
        "isolated": True,
        "no_bytecode": True,
        "version": list(CORE.PYTHON314_VERSION),
    }
    return value


def _unittest_marker(logical, interpreter):
    execution_root = CORE._execution_workspace_path(ROOT)
    target = logical["test_artifact_identity"]
    absolute = str(PurePosixPath(execution_root, target["path"]))
    ids = list(logical["expected_test_ids"])
    executable = _child_executable(interpreter)
    child_identity = _child_file_identity(target, absolute)
    return {
        "schema_version": "offline_unittest_file_result/v1",
        "runner_kind": "stdlib_unittest_single_file_isolated",
        "selection_mode": "selected_ids",
        "workspace": execution_root,
        "import_roots": ["."],
        "path": target["path"],
        "resolved_path": absolute,
        "size_bytes": target["size_bytes"],
        "sha256": target["sha256"],
        "target_identity_before": child_identity,
        "target_identity_after": deepcopy(child_identity),
        "requested_ids": ids,
        "expected_ids": ids,
        "executed_ids": ids,
        "passed_ids": ids,
        "failed_ids": [],
        "skipped_ids": [],
        "discovered_ids": ids,
        "discovered": len(ids),
        "collected": len(ids),
        "passed": len(ids),
        "failed": 0,
        "skipped": 0,
        "exit": 0,
        "result": "PASS",
        "failures": [],
        "executable": executable,
        "python": deepcopy(executable),
        "environment": {
            "clean": True,
            "contaminated_keys": [],
            "cwd": execution_root,
            "sys_path_before_import_roots": [
                "/usr/lib/python314.zip",
                "/usr/lib/python3.14",
                "/usr/lib/python3.14/lib-dynload",
            ],
        },
        "environment_unchanged_during_execution": True,
        "environment_restored": True,
        "stdout_marker_count": 1,
    }


def _pytest_marker(logical):
    target = logical["test_artifact_identity"]
    ids = list(logical["expected_test_ids"])
    return {
        "schema_version": "offline_pytest_file_result/v1",
        "runner_kind": "offline_pytest_style_single_file",
        "path": target["path"],
        "size_bytes": target["size_bytes"],
        "sha256": target["sha256"],
        "expected_ids": ids,
        "executed_ids": ids,
        "collected": len(ids),
        "passed": len(ids),
        "failed": 0,
        "skipped": 0,
        "exit": 0,
        "result": "PASS",
    }


def _physical_records(logical_records):
    logical_by_id = {item["suite_id"]: item for item in logical_records}
    records = []
    for record_id, suite_id, platform, role, count in CORE.PHYSICAL_EXECUTION_DEFINITIONS:
        logical = logical_by_id[suite_id]
        interpreter = CORE._expected_interpreter_identity(role)
        runner = logical["runner_artifact_identity"]["path"]
        if runner.endswith("run_pytest_style_tests.py"):
            prefix = "OFFLINE_PYTEST_FILE_RESULT "
            marker = _pytest_marker(logical)
        else:
            prefix = "OFFLINE_UNITTEST_FILE_RESULT "
            marker = _unittest_marker(logical, interpreter)
        marker_raw = CORE._canonical_json(marker)
        stdout = prefix.encode("ascii") + marker_raw + b"\n"
        argv = CORE._expected_child_argv(ROOT, logical, role, logical["expected_test_ids"])
        records.append({
            "record_id": record_id,
            "suite_id": suite_id,
            "platform": platform,
            "interpreter_role": role,
            "interpreter_identity_before": deepcopy(interpreter),
            "interpreter_identity_after": deepcopy(interpreter),
            "test_artifact_identity_before": dict(logical["test_artifact_identity"]),
            "test_artifact_identity_after": dict(logical["test_artifact_identity"]),
            "runner_artifact_identity_before": dict(logical["runner_artifact_identity"]),
            "runner_artifact_identity_after": dict(logical["runner_artifact_identity"]),
            "expected_test_ids": list(logical["expected_test_ids"]),
            "executed_test_ids": list(logical["expected_test_ids"]),
            "collected": count,
            "passed": count,
            "failed": 0,
            "skipped": 0,
            "exit_code": 0,
            "argv": argv,
            "argv_sha256": CORE._canonical_sha256(argv),
            "environment": dict(CORE.CHILD_ENVIRONMENT),
            "environment_sha256": CORE._canonical_sha256(
                dict(CORE.CHILD_ENVIRONMENT)
            ),
            "stdout": CORE._stream_identity(stdout),
            "stderr": CORE._stream_identity(b""),
            "marker_count": 1,
            "marker_prefix": prefix,
            "marker_raw_sha256": hashlib.sha256(marker_raw).hexdigest(),
            "marker_payload": marker,
            "marker_payload_sha256": CORE._canonical_sha256(marker),
        })
    return records


def _production_observation(source_roles):
    by_path = {item["path"]: item for item in source_roles}
    source = by_path["audit_tools/ros1_camera_only_atomic_launcher.py"]
    source_identity = {
        key: source[key] for key in ("path", "size_bytes", "sha256")
    }
    execution_root = CORE._execution_workspace_path(ROOT)
    archive = (
        "evidence/perception_v2_field_20260814/ros1_launch_source/dabai_u3.launch"
    )
    argv = [
        "/usr/bin/python3.14", "-I", "-S", "-B",
        str(PurePosixPath(execution_root, source["path"])),
        "--mode", "EXECUTE_AUDITED_CAMERA_ONLY",
        "--actual-vendor-launch", str(PurePosixPath(execution_root, archive)),
    ]
    blocked = (
        b"ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
        b"camera_runtime_install_admission_not_bound\n"
    )
    return {
        "not_in_logical_denominator": True,
        "not_in_physical_denominator": True,
        "expected_fail_closed": True,
        "source_identity_before": source_identity,
        "source_identity_after": dict(source_identity),
        "interpreter_identity": CORE._expected_interpreter_identity(
            "system_python314_target"
        ),
        "argv": argv,
        "argv_sha256": CORE._canonical_sha256(argv),
        "environment": dict(CORE.CHILD_ENVIRONMENT),
        "environment_sha256": CORE._canonical_sha256(dict(CORE.CHILD_ENVIRONMENT)),
        "exit_code": 4,
        "stdout": CORE._stream_identity(b""),
        "stderr": CORE._stream_identity(blocked),
        "expected_stderr_sha256": hashlib.sha256(blocked).hexdigest(),
        "blocked_code": "camera_runtime_install_admission_not_bound",
        "formal_consumer": False,
        "delivery_ready": False,
    }


class FormalAdmissionEvidenceAuthorityV4Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source_roles = CORE.collect_source_role_bindings(ROOT)
        cls.dispositions = CORE.source_role_dispositions()
        cls.logical = CORE.logical_suite_records(ROOT, cls.source_roles)
        cls.physical = _physical_records(cls.logical)
        cls.production_observation = _production_observation(cls.source_roles)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".authority-v4-test-", dir=ROOT / "audit_tools"
        )
        temp = Path(self.temporary.name)
        self.policy = CORE.AuthorityPolicy(
            index_relative_path=(temp / "index.json").relative_to(ROOT).as_posix(),
            report_relative_path=(temp / "report.json").relative_to(ROOT).as_posix(),
            canonical_relative_path=(temp / "canonical.json").relative_to(ROOT).as_posix(),
        )
        self.canonical = CORE.build_canonical_payload(
            ROOT, self.source_roles, self.dispositions, self.policy
        )
        self.canonical_identity = _write_json(
            ROOT / self.policy.canonical_relative_path, self.canonical
        )
        self.report = CORE.build_report_payload(
            ROOT, self.canonical_identity, self.source_roles,
            self.physical, self.production_observation,
        )
        self.report_identity = _write_json(
            ROOT / self.policy.report_relative_path, self.report
        )
        self.payload = CORE.build_index_payload(
            self.report_identity, self.canonical_identity,
            self.source_roles, self.policy,
        )
        self.anchor = self._write_index(self.payload)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_index(self, payload):
        return _write_json(ROOT / self.policy.index_relative_path, payload)

    def _rewrite_report(self, mutation):
        report = deepcopy(self.report)
        mutation(report)
        report.pop("report_binding_sha256", None)
        report["report_binding_sha256"] = CORE._canonical_sha256(report)
        identity = _write_json(ROOT / self.policy.report_relative_path, report)
        payload = CORE.build_index_payload(
            identity, self.canonical_identity, self.source_roles, self.policy
        )
        return report, payload

    def _rewrite_canonical(self, mutation):
        canonical = deepcopy(self.canonical)
        mutation(canonical)
        canonical.pop("artifact_binding_sha256", None)
        canonical["artifact_binding_sha256"] = CORE._canonical_sha256(canonical)
        identity = _write_json(ROOT / self.policy.canonical_relative_path, canonical)
        report = deepcopy(self.report)
        report["canonical_source_admission"] = dict(identity)
        report.pop("report_binding_sha256", None)
        report["report_binding_sha256"] = CORE._canonical_sha256(report)
        report_identity = _write_json(ROOT / self.policy.report_relative_path, report)
        payload = CORE.build_index_payload(
            report_identity, identity, self.source_roles, self.policy
        )
        return canonical, payload

    def test_semantic_validator_cannot_select_without_external_index_anchor(self):
        result = CORE.validate_formal_admission_evidence_authority_v4(
            ROOT, self.payload, self.policy
        )
        self.assertTrue(result["semantic_validated_pass"], result["failures"])
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertIsNone(result["current_evidence"])

    def test_external_anchor_selects_one_blocked_offline_current(self):
        result = CORE.load_and_resolve_formal_admission_evidence_authority_v4(
            ROOT, self.anchor, self.policy
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertEqual(result["current_evidence"]["evidence_id"], CORE.CURRENT_EVIDENCE_ID)
        for key in (
            "accepted_by_formal_field_evidence_consumer", "regression_passed",
            "delivery_ready", "authorizes_field_delivery", "formal_tf_pass",
            "formal_3d_pass", "formal_latency_pass",
            "ros1_noetic_runtime_verified", "ros1_noetic_build_install_verified",
            "ros1_noetic_field_install_pass",
        ):
            self.assertFalse(result[key], key)
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)

    def test_zero_multiple_and_old_v4_repromotion_fail_closed(self):
        zero = deepcopy(self.payload)
        zero["entries"][1]["is_current"] = False
        multiple = deepcopy(self.payload)
        multiple["entries"][0]["is_current"] = True
        old = json.loads((ROOT / CORE.PREDECESSOR_INDEX_IDENTITY["path"]).read_text())
        for payload in (zero, multiple, old):
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])
            self.assertIsNone(result["current_evidence"])

    def test_wrong_predecessor_and_lineage_self_cycle_fail(self):
        for mutation in ("wrong", "cycle"):
            payload = deepcopy(self.payload)
            if mutation == "wrong":
                payload["predecessor_authority_index"]["sha256"] = "0" * 64
            else:
                payload["entries"][1]["predecessor_evidence_id"] = CORE.CURRENT_EVIDENCE_ID
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_external_anchor_path_size_and_sha_are_all_exact(self):
        for key, value in (
            ("path", CORE.INDEX_RELATIVE_PATH),
            ("size_bytes", self.anchor["size_bytes"] + 1),
            ("sha256", "0" * 64),
        ):
            anchor = dict(self.anchor)
            anchor[key] = value
            result = CORE.load_and_resolve_formal_admission_evidence_authority_v4(
                ROOT, anchor, self.policy
            )
            self.assertFalse(result["validated_pass"])
            self.assertIsNone(result["current_evidence"])

    def test_source_role_omission_duplicate_and_drift_fail(self):
        for mode in ("omit", "duplicate", "drift"):
            payload = deepcopy(self.payload)
            if mode == "omit":
                payload["source_roles"].pop()
            elif mode == "duplicate":
                payload["source_roles"][-1] = deepcopy(payload["source_roles"][0])
            else:
                payload["source_roles"][0]["sha256"] = "0" * 64
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_canonical_disposition_or_live_overlay_drift_fails(self):
        def disposition(value):
            value["source_role_dispositions"][0]["disposition"] = "BOUND_FIELD"

        def overlay(value):
            value["live_overlay_binding"]["entries"][0]["sha256"] = "0" * 64

        for mutation in (disposition, overlay):
            unused, payload = self._rewrite_canonical(mutation)
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_logical_and_physical_denominators_are_recomputed(self):
        def logical(report):
            report["test_matrix"]["logical_collected"] = 154

        def physical(report):
            report["test_matrix"]["physical_execution_records"].pop()
            report["test_matrix"]["physical_collected"] = 263

        for mutation in (logical, physical):
            unused, payload = self._rewrite_report(mutation)
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_forged_marker_rehash_and_copied_record_still_fail(self):
        def forged(report):
            record = report["test_matrix"]["physical_execution_records"][0]
            record["marker_payload"]["executed_ids"] = []
            raw = CORE._canonical_json(record["marker_payload"])
            record["marker_raw_sha256"] = hashlib.sha256(raw).hexdigest()
            record["marker_payload_sha256"] = CORE._canonical_sha256(
                record["marker_payload"]
            )
            stdout = record["marker_prefix"].encode() + raw + b"\n"
            record["stdout"] = CORE._stream_identity(stdout)

        def copied(report):
            records = report["test_matrix"]["physical_execution_records"]
            replacement = deepcopy(records[0])
            replacement["record_id"] = records[1]["record_id"]
            records[1] = replacement

        for mutation in (forged, copied):
            unused, payload = self._rewrite_report(mutation)
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_arbitrary_or_split_interpreter_target_identity_fails(self):
        def arbitrary(report):
            record = report["test_matrix"]["physical_execution_records"][0]
            for key in ("interpreter_identity_before", "interpreter_identity_after"):
                record[key]["resolved_target"]["size_bytes"] = 1
                record[key]["resolved_target"]["sha256"] = "0" * 64

        def split(report):
            record = report["test_matrix"]["physical_execution_records"][1]
            record["interpreter_identity_after"]["resolved_target"]["sha256"] = "1" * 64

        for mutation in (arbitrary, split):
            unused, payload = self._rewrite_report(mutation)
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_production_anchor_self_report_and_field_promotion_fail(self):
        def self_report(report):
            report["production_authority_state"]["camera_runtime_install_admission_authority_bound"] = True

        def promote(report):
            report["gate_state"]["delivery_ready"] = True
            report["delivery_ready"] = True

        for mutation in (self_report, promote):
            unused, payload = self._rewrite_report(mutation)
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])

    def test_filename_mtime_selection_and_nested_type_substitution_fail(self):
        payload = deepcopy(self.payload)
        payload["uses_filename_or_mtime_authority"] = True
        payload["gate_state"]["delivery_ready"] = 0
        result = CORE.validate_formal_admission_evidence_authority_v4(
            ROOT, payload, self.policy
        )
        self.assertFalse(result["semantic_validated_pass"])
        self.assertFalse(CORE._same({"x": False}, {"x": 0}))
        self.assertFalse(CORE._same({"x": 5015}, {"x": 5015.0}))

    def test_strict_index_json_rejects_duplicate_key_and_nonfinite(self):
        for raw in (
            b'{"schema_version":"x","schema_version":"y"}\n',
            b'{"value":NaN}\n',
        ):
            path = ROOT / self.policy.index_relative_path
            path.write_bytes(raw)
            anchor = {
                "path": self.policy.index_relative_path,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            result = CORE.load_and_resolve_formal_admission_evidence_authority_v4(
                ROOT, anchor, self.policy
            )
            self.assertFalse(result["validated_pass"])
            self.assertIn(
                "formal_authority_v4_index_strict_json_invalid",
                result["failures"],
            )

    def test_malformed_unhashable_ids_and_paths_return_structured_failure(self):
        mutations = []
        value = deepcopy(self.payload)
        value["entries"][0]["evidence_id"] = []
        mutations.append(value)
        value = deepcopy(self.payload)
        value["source_roles"][0]["path"] = []
        mutations.append(value)
        for payload in mutations:
            result = CORE.validate_formal_admission_evidence_authority_v4(
                ROOT, payload, self.policy
            )
            self.assertFalse(result["semantic_validated_pass"])
            self.assertTrue(result["failures"])

    def test_old_resolver_cannot_select_new_index_anchor(self):
        result = OLD_AUTHORITY.load_and_resolve_formal_admission_evidence_authority_v3(
            ROOT, OLD_AUTHORITY.successor_generation_spec(), self.anchor
        )
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v3_index_anchor_path_mismatch",
            result["failures"],
        )

    def test_production_resolver_is_fail_closed_until_external_anchors_exist(self):
        previous_core = PRODUCTION.CORE_SOURCE_TRUST_ANCHOR
        previous_index = PRODUCTION.PRODUCTION_INDEX_TRUST_ANCHOR
        try:
            PRODUCTION.CORE_SOURCE_TRUST_ANCHOR = None
            PRODUCTION.PRODUCTION_INDEX_TRUST_ANCHOR = None
            result = PRODUCTION.load_and_resolve_current_authority(ROOT)
            self.assertFalse(result["validated_pass"])
            self.assertFalse(
                result["accepted_as_offline_release_selection_authority"]
            )
            self.assertIsNone(result["current_evidence"])
            self.assertIn(
                "formal_authority_v4_core_source_anchor_not_configured",
                result["failures"],
            )
            self.assertFalse(result["core_source_anchor_configured"])
            self.assertFalse(result["production_anchor_configured"])
        finally:
            PRODUCTION.CORE_SOURCE_TRUST_ANCHOR = previous_core
            PRODUCTION.PRODUCTION_INDEX_TRUST_ANCHOR = previous_index

    def test_production_wrapper_ignores_ambient_fake_core_and_meta_finder(self):
        calls = {"module": 0, "finder": 0}
        fake = types.ModuleType(
            "audit_tools.formal_admission_evidence_authority_v4_core"
        )

        def fake_resolver(*unused_args, **unused_kwargs):
            calls["module"] += 1
            return {"validated_pass": True}

        fake.load_and_resolve_formal_admission_evidence_authority_v4 = fake_resolver

        class Finder:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.endswith("formal_admission_evidence_authority_v4_core"):
                    calls["finder"] += 1
                return None

        name = "audit_tools.formal_admission_evidence_authority_v4_core"
        previous_module = sys.modules.get(name)
        previous_anchor = PRODUCTION.CORE_SOURCE_TRUST_ANCHOR
        finder = Finder()
        try:
            sys.modules[name] = fake
            sys.meta_path.insert(0, finder)
            PRODUCTION.CORE_SOURCE_TRUST_ANCHOR = CORE.artifact_identity(
                ROOT, PRODUCTION.CORE_SOURCE_RELATIVE_PATH
            )
            loaded, identity, failures = PRODUCTION._load_exact_core(ROOT)
            self.assertEqual(failures, [])
            self.assertIsNotNone(loaded)
            self.assertIsNot(loaded, fake)
            self.assertEqual(identity, PRODUCTION.CORE_SOURCE_TRUST_ANCHOR)
            self.assertEqual(calls, {"module": 0, "finder": 0})
        finally:
            PRODUCTION.CORE_SOURCE_TRUST_ANCHOR = previous_anchor
            sys.meta_path.remove(finder)
            if previous_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module


if __name__ == "__main__":
    unittest.main()
