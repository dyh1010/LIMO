"""Fail-closed tests for the parameterized v2 offline authority."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from audit_tools import formal_admission_evidence_authority_v2 as AUTH


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {
        "path": path.as_posix(),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


class FormalAdmissionEvidenceAuthorityV2Test(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in (
            AUTH.PREDECESSOR_INDEX_IDENTITY["path"],
            AUTH.SUPERSEDED_REPORT["path"],
        ):
            source = ROOT.joinpath(*Path(relative).parts)
            target = self.root.joinpath(*Path(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target))

        self.source_root = "ros1_overlay_src/limo_cleanup_ros1_perception"
        source_relative = self.source_root + "/src/limo_cleanup_ros1_perception/runtime.py"
        source_path = self.root.joinpath(*Path(source_relative).parts)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_raw = b"READ_ONLY = True\n"
        source_path.write_bytes(source_raw)
        entries = [{
            "path": "src/limo_cleanup_ros1_perception/runtime.py",
            "size_bytes": len(source_raw),
            "sha256": hashlib.sha256(source_raw).hexdigest(),
        }]
        canonical = {
            "schema_version": 1,
            "binding_kind": "canonical_project_overlay",
            "canonical_source_root": self.source_root,
            "file_count": 1,
            "source_contract_pass": True,
            "indexer_only_detected": False,
            "test_only": False,
            "architecture_blockers": [],
            "contract_sha256": "1" * 64,
            "entries": entries,
            "source_set_sha256": AUTH._canonical_json_sha(entries),
        }
        canonical["binding_sha256"] = AUTH._canonical_json_sha(canonical)
        self.canonical_relative = (
            "evidence/perception_v2_offline_20260813/"
            "ros1_noetic_canonical_source_admission_20260815_v3_test.json"
        )
        canonical_target = self.root.joinpath(*Path(self.canonical_relative).parts)
        write_json(canonical_target, canonical)
        unused, canonical_identity, unused_raw = AUTH._regular_identity(
            self.root, self.canonical_relative
        )
        self.canonical_expected = {
            "schema_version": 1,
            "binding_kind": "canonical_project_overlay",
            "canonical_source_root": self.source_root,
            "file_count": 1,
            "source_contract_pass": True,
            "indexer_only_detected": False,
            "test_only": False,
            "architecture_blockers": [],
        }

        self.report_relative = (
            "evidence/perception_v2_offline_20260813/"
            "frozen_offline_regression_20260815_runtime_source_v2_test.json"
        )
        report = self.make_report(canonical_identity)
        report_target = self.root.joinpath(*Path(self.report_relative).parts)
        write_json(report_target, report)
        unused, report_identity, unused_raw = AUTH._regular_identity(
            self.root, self.report_relative
        )
        self.index_relative = (
            "evidence/perception_v2_offline_20260813/"
            "ros1_formal_admission_evidence_authority_index_20260815_v2_test.json"
        )
        self.spec = AUTH.make_generation_spec(
            current_report_identity=report_identity,
            canonical_child_identity=canonical_identity,
            index_relative_path=self.index_relative,
            canonical_expected=self.canonical_expected,
        )
        self.payload = AUTH.expected_index_payload(self.spec)
        index_target = self.root.joinpath(*Path(self.index_relative).parts)
        index_target.parent.mkdir(parents=True, exist_ok=True)
        AUTH.write_index_exclusive(index_target, self.payload)
        self.anchor = AUTH.index_identity(self.root, self.index_relative)

    def tearDown(self):
        self.temporary.cleanup()

    def make_pytest_ledger(self):
        case_counts = (
            5, 1, 2, 2, 9, 2, 6, 7, 5, 7, 5, 18, 17, 8, 15, 2,
        )
        self.assertEqual(sum(case_counts), AUTH.EXPECTED_PYTEST_CASE_TOTAL)
        records = []
        for relative, case_count in zip(
                AUTH.EXPECTED_PYTEST_FILE_PATHS, case_counts):
            target = self.root.joinpath(*Path(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# " + relative, ""]
            for index in range(case_count):
                lines.extend((
                    "def test_case_{:03d}():".format(index),
                    "    pass",
                    "",
                ))
            target.write_bytes("\n".join(lines).encode("utf-8"))
            unused, identity, unused_raw = AUTH._regular_identity(
                self.root, relative
            )
            expected_ids = list(AUTH._static_pytest_case_ids(self.root, relative))
            marker = {
                "schema_version": AUTH.PYTEST_FILE_RESULT_SCHEMA_VERSION,
                "runner_kind": AUTH.PYTEST_FILE_RESULT_RUNNER_KIND,
                "path": relative,
                "size_bytes": identity["size_bytes"],
                "sha256": identity["sha256"],
                "expected_ids": expected_ids,
                "executed_ids": expected_ids,
                "collected": case_count,
                "passed": case_count,
                "failed": 0,
                "skipped": 0,
                "exit": 0,
                "result": "PASS",
            }
            marker_raw = json.dumps(
                marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            stdout = AUTH.PYTEST_FILE_RESULT_PREFIX + marker_raw.decode("utf-8") + "\n"
            stdout_raw = stdout.encode("utf-8")
            argv = [
                str(self.root / "trusted-python.exe"), "-I", "-B",
                str(self.root / "audit_tools/run_pytest_style_tests.py"),
                "--single-file", "--workspace", str(self.root),
                "--target", str(target),
            ]
            for import_root in AUTH.EXPECTED_PYTEST_POLICY["import_roots"]:
                argv.extend(("--import-root", import_root))
            for case_id in expected_ids:
                argv.extend(("--expected-id", case_id))
            empty_sha = hashlib.sha256(b"").hexdigest()
            records.append({
                "allocations": [{
                    "scope": "frozen_full",
                    "suite_id": Path(relative).name,
                    "expected_ids": expected_ids,
                }],
                "collected": case_count,
                "command": {
                    "argv": argv,
                    "cwd": str(self.root),
                    "duration_sec": 0.01,
                    "exit_code": 0,
                    "stderr_head": "",
                    "stderr_length_bytes": 0,
                    "stderr_length_chars": 0,
                    "stderr_sha256": empty_sha,
                    "stderr_tail": "",
                    "stdout_head": stdout[:2000],
                    "stdout_length_bytes": len(stdout_raw),
                    "stdout_length_chars": len(stdout),
                    "stdout_sha256": hashlib.sha256(stdout_raw).hexdigest(),
                    "stdout_tail": stdout[-2000:],
                    "timed_out": False,
                },
                "executed_ids": expected_ids,
                "expected_ids": expected_ids,
                "failed": 0,
                "failures": [],
                "marker_json_length_bytes": len(marker_raw),
                "marker_json_sha256": hashlib.sha256(marker_raw).hexdigest(),
                "marker_payload": marker,
                "passed": case_count,
                "path": relative,
                "post_identity": identity,
                "pre_identity": identity,
                "skipped": 0,
                "source_unchanged": True,
                "validated_pass": True,
            })
        policy = dict(AUTH.EXPECTED_PYTEST_POLICY)
        policy["fixed_cwd"] = str(self.root)
        return {
            "pytest_style_file_execution_policy": policy,
            "pytest_style_file_inventory": {
                "ordered_paths": list(AUTH.EXPECTED_PYTEST_FILE_PATHS),
                "unique_file_count": AUTH.EXPECTED_PYTEST_FILE_COUNT,
                "failures": [],
            },
            "pytest_style_file_records": records,
        }

    def make_report(self, canonical_identity):
        matrix = dict(AUTH.DEFAULT_TEST_COUNTS, failures=[])
        matrix.update(self.make_pytest_ledger())
        return {
            "report_kind": "perception_v2_frozen_offline_regression",
            "schema_version": 1,
            "read_only": True,
            "authorizes_motion": False,
            "regression_passed": False,
            "delivery_ready": False,
            "publishes_ros_messages": False,
            "ros_graph_started": False,
            "camera_opened": False,
            "hardware_connected": False,
            "test_matrix": matrix,
            "source_drift": {"unchanged": True},
            "delivery_gate_summary": {
                "delivery_ready": False,
                "formal_field_evidence_gate": {
                    "formal_four_scene_frame_denominator": 0,
                    "formal_tf_pass": False,
                    "formal_3d_pass": False,
                    "formal_latency_pass": False,
                    "validated_pass": False,
                },
                "ros1_field_gate": {
                    "source_contract_pass": True,
                    "source_implementation_pass": True,
                    "install_evidence_pass": False,
                    "validated_pass": False,
                    "field_evidence_blockers": [
                        "ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING"
                    ],
                    "build_install_blockers": [
                        "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED"
                    ],
                },
                "ros1_canonical_source_admission_gate": {
                    "manifest_identity": canonical_identity,
                    "validated_pass": True,
                },
                "evidence_authority_gate": {
                    "current_evidence_id": (
                        AUTH.EMBEDDED_RUNNER_AUTHORITY_EVIDENCE_ID
                    ),
                    "authorizes_field_delivery": False,
                    "delivery_ready": False,
                },
                "environment_gate": {
                    "source_build_failure": False,
                    "active_blockers": ["WSL_E_ACCESSDENIED_BEFORE_SHELL_OR_BUILD"],
                },
                "delivery_blockers": list(AUTH.DEFAULT_REPORT_BLOCKERS),
                "architecture_blockers": [],
                "field_evidence_blockers": [
                    "ROS1_NOETIC_FIELD_INSTALL_EVIDENCE_MISSING"
                ],
                "build_install_blockers": [
                    "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED"
                ],
                "formal_field_blockers": [
                    "FORMAL_3D_NOT_VALIDATED",
                    "FORMAL_FOUR_SCENE_DENOMINATOR_ZERO",
                    "FORMAL_LATENCY_NOT_VALIDATED",
                    "FORMAL_TF_NOT_VALIDATED",
                ],
            },
        }

    def resolve(self, spec=None, anchor=None):
        return AUTH.load_and_resolve_formal_admission_evidence_authority_v2(
            self.root,
            self.spec if spec is None else spec,
            self.anchor if anchor is None else anchor,
        )

    def validate(self, payload=None, spec=None):
        return AUTH.validate_formal_admission_evidence_authority_v2(
            self.root, self.payload if payload is None else payload,
            self.spec if spec is None else spec,
        )

    def assert_failed(self, result, prefix):
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertFalse(result["formal_tf_pass"])
        self.assertFalse(result["formal_3d_pass"])
        self.assertFalse(result["formal_latency_pass"])
        self.assertFalse(result["ros1_noetic_field_install_pass"])
        self.assertFalse(result["ros1_noetic_build_install_verified"])
        self.assertFalse(result["ros1_source_implementation_complete"])
        self.assertFalse(
            result["historical_runtime_not_implemented_observation_superseded"]
        )
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(
            any(item.startswith(prefix) for item in result["failures"]),
            result["failures"],
        )

    def validate_report_mutation(self, mutate):
        report_path = self.root.joinpath(*Path(self.report_relative).parts)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        mutate(report)
        write_json(report_path, report)
        unused, identity, unused_raw = AUTH._regular_identity(
            self.root, self.report_relative
        )
        spec = deepcopy(self.spec)
        spec["current_report_identity"] = identity
        payload = AUTH.expected_index_payload(spec)
        return self.validate(payload, spec)

    def test_valid_externally_anchored_index_selects_exactly_one_current(self):
        result = self.resolve()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(
            result["current_evidence"]["evidence_id"],
            AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
        )
        self.assertEqual(len(result["artifact_identities"]), 4)
        self.assertEqual(result["index_identity"], self.anchor)
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertFalse(result["formal_tf_pass"])
        self.assertFalse(result["formal_3d_pass"])
        self.assertFalse(result["formal_latency_pass"])
        self.assertFalse(result["ros1_noetic_build_install_verified"])
        self.assertTrue(result["ros1_source_implementation_complete"])
        self.assertEqual(result["ros1_source_architecture_blockers"], [])
        self.assertTrue(
            result["historical_runtime_not_implemented_observation_superseded"]
        )
        self.assertEqual(self.payload["entries"][0]["status"], "SUPERSEDED_NON_CURRENT")
        self.assertFalse(self.payload["entries"][0]["is_current"])

    def test_missing_or_extra_top_level_state_fails_closed(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                value = deepcopy(self.payload)
                if mutation == "missing":
                    value.pop("generation_scope")
                else:
                    value["mtime"] = 0
                self.assert_failed(
                    self.validate(value), "formal_authority_v2_top_level_keys_invalid"
                )

    def test_zero_or_multiple_current_fails_closed(self):
        zero = deepcopy(self.payload)
        zero["entries"][1]["is_current"] = False
        self.assert_failed(
            self.validate(zero), "formal_authority_v2_current_count_invalid"
        )
        multiple = deepcopy(self.payload)
        multiple["entries"][0]["is_current"] = True
        self.assert_failed(
            self.validate(multiple), "formal_authority_v2_current_count_invalid"
        )

    def test_report_path_size_hash_status_and_generation_mismatch_fail_closed(self):
        mutations = (
            ("path", AUTH.SUPERSEDED_REPORT["path"]),
            ("size_bytes", 1),
            ("sha256", "0" * 64),
            ("status", "CURRENT"),
            ("generation_id", "wrong_generation"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                payload = deepcopy(self.payload)
                payload["entries"][1][key] = value
                self.assert_failed(
                    self.validate(payload),
                    "formal_authority_v2_entry_mismatch:" + AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
                )

    def test_generation_scope_and_filename_mtime_selection_are_exact(self):
        for key, value in (
            ("generation_scope", "field_delivery"),
            ("filename_mtime_selection_forbidden", False),
            ("uses_filename_or_mtime_authority", True),
            ("selection_authority", "NEWEST_MTIME"),
        ):
            with self.subTest(key=key):
                payload = deepcopy(self.payload)
                payload[key] = value
                self.assert_failed(
                    self.validate(payload), "formal_authority_v2_top_level_mismatch:" + key
                )

    def test_extra_duplicate_or_role_swapped_artifact_fails_closed(self):
        extra = deepcopy(self.payload)
        extra["entries"].append(deepcopy(extra["entries"][0]))
        extra["entries"][-1]["evidence_id"] = "extra"
        self.assert_failed(extra_result := self.validate(extra), "formal_authority_v2_entry_count_invalid")
        self.assertFalse(extra_result["delivery_ready"])
        duplicate = deepcopy(self.payload)
        duplicate["entries"][1]["evidence_id"] = duplicate["entries"][0]["evidence_id"]
        self.assert_failed(
            self.validate(duplicate), "formal_authority_v2_duplicate_evidence_id"
        )
        swapped_spec = deepcopy(self.spec)
        swapped_spec["current_report_identity"] = dict(
            swapped_spec["canonical_child_identity"]
        )
        self.assert_failed(
            self.validate(spec=swapped_spec),
            "formal_authority_v2_spec_artifact_path_collision",
        )

    def test_child_parent_role_path_and_hash_are_exact(self):
        for key, value in (
            ("parent_evidence_id", AUTH.SUPERSEDED_REPORT["evidence_id"]),
            ("role", "field_evidence"),
            ("path", self.report_relative),
            ("sha256", "f" * 64),
        ):
            with self.subTest(key=key):
                payload = deepcopy(self.payload)
                payload["child_artifacts"][0][key] = value
                self.assert_failed(
                    self.validate(payload), "formal_authority_v2_child_artifacts_invalid"
                )

    def test_every_field_delivery_build_tf_3d_and_latency_claim_is_fixed_false(self):
        mutations = (
            ("authorizes_field_delivery",),
            ("gate_state", "delivery_ready"),
            ("gate_state", "regression_passed"),
            ("gate_state", "formal_tf_pass"),
            ("gate_state", "formal_3d_pass"),
            ("gate_state", "formal_latency_pass"),
            ("gate_state", "ros1_noetic_field_install_pass"),
            ("gate_state", "ros1_noetic_build_install_verified"),
        )
        for path in mutations:
            with self.subTest(path=path):
                payload = deepcopy(self.payload)
                target = payload
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = True
                self.assert_failed(
                    self.validate(payload),
                    "formal_authority_v2_top_level_mismatch:" + path[0],
                )

    def test_current_report_bytes_and_semantics_are_recomputed(self):
        report_path = self.root.joinpath(*Path(self.report_relative).parts)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["delivery_ready"] = True
        write_json(report_path, report)
        unused, identity, unused_raw = AUTH._regular_identity(self.root, self.report_relative)
        spec = deepcopy(self.spec)
        spec["current_report_identity"] = identity
        payload = AUTH.expected_index_payload(spec)
        self.assert_failed(
            self.validate(payload, spec),
            "formal_authority_v2_current_report_semantic_mismatch:delivery_ready",
        )

    def test_report_counts_source_drift_and_required_blockers_are_recomputed(self):
        report_path = self.root.joinpath(*Path(self.report_relative).parts)
        base = json.loads(report_path.read_text(encoding="utf-8"))
        mutations = (
            ("count",), ("source",), ("blocker",), ("install",),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                report = deepcopy(base)
                if mutation == ("count",):
                    report["test_matrix"]["current_generation_passed"] = 68
                    prefix = "formal_authority_v2_current_report_test_count_mismatch:"
                elif mutation == ("source",):
                    report["source_drift"]["unchanged"] = False
                    prefix = "formal_authority_v2_current_report_source_drift_not_unchanged"
                elif mutation == ("blocker",):
                    report["delivery_gate_summary"]["delivery_blockers"] = []
                    prefix = "formal_authority_v2_current_report_required_blockers_missing"
                else:
                    report["delivery_gate_summary"]["ros1_field_gate"]["install_evidence_pass"] = True
                    prefix = "formal_authority_v2_current_report_field_gate_mismatch:"
                write_json(report_path, report)
                unused, identity, unused_raw = AUTH._regular_identity(self.root, self.report_relative)
                spec = deepcopy(self.spec)
                spec["current_report_identity"] = identity
                payload = AUTH.expected_index_payload(spec)
                self.assert_failed(self.validate(payload, spec), prefix)
        write_json(report_path, base)

    def test_canonical_bytes_semantics_binding_and_live_source_are_recomputed(self):
        canonical_path = self.root.joinpath(*Path(self.canonical_relative).parts)
        original = json.loads(canonical_path.read_text(encoding="utf-8"))
        changed = deepcopy(original)
        changed["source_contract_pass"] = False
        changed["binding_sha256"] = AUTH._canonical_json_sha({
            key: value for key, value in changed.items() if key != "binding_sha256"
        })
        write_json(canonical_path, changed)
        unused, identity, unused_raw = AUTH._regular_identity(self.root, self.canonical_relative)
        spec = deepcopy(self.spec)
        spec["canonical_child_identity"] = identity
        payload = AUTH.expected_index_payload(spec)
        self.assert_failed(
            self.validate(payload, spec),
            "formal_authority_v2_canonical_semantic_mismatch:source_contract_pass",
        )
        write_json(canonical_path, original)
        source = self.root / self.source_root / original["entries"][0]["path"]
        source.write_bytes(source.read_bytes() + b"# drift\n")
        self.assert_failed(
            self.validate(), "formal_authority_v2_canonical_live_source_mismatch:"
        )

    def test_predecessor_index_and_report_bytes_are_immutable_inputs(self):
        for identity, artifact_id in (
            (AUTH.PREDECESSOR_INDEX_IDENTITY, "predecessor_index"),
            (AUTH.SUPERSEDED_REPORT, AUTH.SUPERSEDED_REPORT["evidence_id"]),
        ):
            with self.subTest(artifact_id=artifact_id):
                path = self.root.joinpath(*Path(identity["path"]).parts)
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.assert_failed(
                    self.validate(), "formal_authority_v2_artifact_size_mismatch:" + artifact_id
                )
                path.write_bytes(original)

    def test_index_external_path_size_and_hash_anchor_rejects_drift(self):
        path = self.root.joinpath(*Path(self.index_relative).parts)
        path.write_bytes(path.read_bytes() + b" ")
        result = self.resolve()
        self.assert_failed(result, "formal_authority_v2_index_size_mismatch")
        self.assertIn("formal_authority_v2_index_sha256_mismatch", result["failures"])
        wrong_path = deepcopy(self.anchor)
        wrong_path["path"] = self.report_relative
        self.assert_failed(
            self.resolve(anchor=wrong_path),
            "formal_authority_v2_index_anchor_path_mismatch",
        )

    def test_duplicate_key_nonfinite_and_nonjson_artifacts_fail_strictly(self):
        index_path = self.root.joinpath(*Path(self.index_relative).parts)
        for raw in (
            b'{"schema_version":1,"schema_version":1}',
            b'{"value":NaN}',
        ):
            with self.subTest(raw=raw):
                index_path.write_bytes(raw)
                anchor = AUTH.index_identity(self.root, self.index_relative)
                self.assert_failed(
                    self.resolve(anchor=anchor),
                    "formal_authority_v2_index_strict_json_invalid",
                )
        report_path = self.root.joinpath(*Path(self.report_relative).parts)
        report_path.write_bytes(b"not json")
        unused, identity, unused_raw = AUTH._regular_identity(self.root, self.report_relative)
        spec = deepcopy(self.spec)
        spec["current_report_identity"] = identity
        payload = AUTH.expected_index_payload(spec)
        self.assert_failed(
            self.validate(payload, spec),
            "formal_authority_v2_artifact_strict_json_invalid:" + AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
        )

    def test_unsafe_escape_linklike_and_nonregular_paths_fail_closed(self):
        unsafe = deepcopy(self.spec)
        unsafe["current_report_identity"]["path"] = "../escape.json"
        self.assert_failed(
            self.validate(spec=unsafe), "formal_authority_v2_current_report_path_invalid"
        )
        original = AUTH._is_linklike

        def linked(path):
            if Path(path).name == Path(self.report_relative).name:
                return True
            return original(Path(path))

        with mock.patch.object(AUTH, "_is_linklike", side_effect=linked):
            self.assert_failed(
                self.validate(),
                "formal_authority_v2_artifact_unreadable:" + AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
            )
        report_path = self.root.joinpath(*Path(self.report_relative).parts)
        report_path.unlink()
        report_path.mkdir()
        self.assert_failed(
            self.validate(),
            "formal_authority_v2_artifact_unreadable:" + AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
        )

    def test_exclusive_creation_refuses_overwrite_and_anchor_is_mandatory(self):
        target = self.root / "new-index.json"
        first = AUTH.write_index_exclusive(target, self.payload)
        self.assertGreater(first["size_bytes"], 0)
        with self.assertRaises(FileExistsError):
            AUTH.write_index_exclusive(target, self.payload)
        missing_anchor = {}
        self.assert_failed(
            self.resolve(anchor=missing_anchor),
            "formal_authority_v2_index_anchor_identity_schema_invalid",
        )

    def test_spec_cannot_downgrade_canonical_or_omit_latency_blocker(self):
        cases = []
        canonical_false = deepcopy(self.spec)
        canonical_false["canonical_expected"]["source_contract_pass"] = False
        cases.append((canonical_false, "formal_authority_v2_canonical_source_not_passed"))
        test_only = deepcopy(self.spec)
        test_only["canonical_expected"]["test_only"] = True
        cases.append((test_only, "formal_authority_v2_canonical_test_only"))
        no_latency = deepcopy(self.spec)
        no_latency["gate_blockers"].remove("FORMAL_LATENCY_NOT_VALIDATED")
        cases.append((no_latency, "formal_authority_v2_gate_blockers_incomplete"))
        for spec, prefix in cases:
            with self.subTest(prefix=prefix):
                self.assert_failed(self.validate(spec=spec), prefix)

    def test_source_implementation_layering_gate_fields_are_exact(self):
        mutations = (
            ("ros1_source_implementation_complete", False),
            ("ros1_source_architecture_blockers", [
                "ROS1_NOETIC_PERCEPTION_RUNTIME_NOT_IMPLEMENTED"
            ]),
            ("historical_runtime_not_implemented_observation_superseded", False),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                payload = deepcopy(self.payload)
                payload["gate_state"][key] = value
                self.assert_failed(
                    self.validate(payload),
                    "formal_authority_v2_top_level_mismatch:gate_state",
                )

    def test_pytest_file_ledger_rejects_deleted_record_with_unchanged_totals(self):
        def delete_record(report):
            report["test_matrix"]["pytest_style_file_records"].pop()

        result = self.validate_report_mutation(delete_record)
        self.assert_failed(
            result, "formal_authority_v2_pytest_record_denominator_invalid"
        )
        self.assertIn("formal_authority_v2_pytest_record_paths_invalid", result["failures"])

    def test_pytest_file_ledger_rejects_duplicate_path_and_hash(self):
        def duplicate_equal_count_record(report):
            records = report["test_matrix"]["pytest_style_file_records"]
            self.assertEqual(records[2]["collected"], records[3]["collected"])
            records[3] = deepcopy(records[2])

        result = self.validate_report_mutation(duplicate_equal_count_record)
        self.assert_failed(result, "formal_authority_v2_pytest_duplicate_path")
        self.assertIn("formal_authority_v2_pytest_hash_set_invalid", result["failures"])

    def test_pytest_file_ledger_rejects_id_and_marker_tamper(self):
        report = json.loads(
            self.root.joinpath(*Path(self.report_relative).parts).read_text(
                encoding="utf-8"
            )
        )
        matrix = report["test_matrix"]
        id_tamper = deepcopy(matrix)
        id_tamper["pytest_style_file_records"][0]["expected_ids"][0] = (
            AUTH.EXPECTED_PYTEST_FILE_PATHS[0] + "::test_substituted"
        )
        failures = AUTH._validate_pytest_file_execution_evidence(
            id_tamper, self.root
        )
        self.assertTrue(any(
            item.endswith("expected_ids_mismatch") for item in failures
        ), failures)

        marker_tamper = deepcopy(matrix)
        marker_tamper["pytest_style_file_records"][0]["marker_payload"][
            "result"
        ] = "FAIL"
        failures = AUTH._validate_pytest_file_execution_evidence(
            marker_tamper, self.root
        )
        self.assertTrue(any(
            item.endswith("marker_semantic_mismatch") for item in failures
        ), failures)
        self.assertTrue(any(
            item.endswith("marker_canonical_identity_mismatch")
            for item in failures
        ), failures)

    def test_pytest_file_ledger_rejects_synchronized_equal_total_id_substitution(self):
        def substitute_every_self_report(report):
            record = report["test_matrix"]["pytest_style_file_records"][0]
            old_id = record["expected_ids"][0]
            fake_id = record["path"] + "::test_equal_total_substitution"
            record["expected_ids"][0] = fake_id
            record["executed_ids"][0] = fake_id
            record["allocations"][0]["expected_ids"][0] = fake_id
            marker = record["marker_payload"]
            marker["expected_ids"][0] = fake_id
            marker["executed_ids"][0] = fake_id
            marker_raw = json.dumps(
                marker, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")
            ).encode("utf-8")
            record["marker_json_length_bytes"] = len(marker_raw)
            record["marker_json_sha256"] = hashlib.sha256(marker_raw).hexdigest()
            stdout = (
                AUTH.PYTEST_FILE_RESULT_PREFIX
                + marker_raw.decode("utf-8") + "\n"
            )
            stdout_raw = stdout.encode("utf-8")
            command = record["command"]
            command["argv"] = [
                fake_id if value == old_id else value
                for value in command["argv"]
            ]
            command["stdout_head"] = stdout[:2000]
            command["stdout_tail"] = stdout[-2000:]
            command["stdout_length_bytes"] = len(stdout_raw)
            command["stdout_length_chars"] = len(stdout)
            command["stdout_sha256"] = hashlib.sha256(stdout_raw).hexdigest()

        result = self.validate_report_mutation(substitute_every_self_report)
        self.assertEqual(
            json.loads(
                self.root.joinpath(*Path(self.report_relative).parts).read_text(
                    encoding="utf-8"
                )
            )["test_matrix"]["pytest_style_file_records"][0]["collected"],
            5,
        )
        self.assert_failed(
            result, "formal_authority_v2_pytest_record:0:expected_ids_mismatch"
        )


class ProductionFormalAdmissionEvidenceAuthorityV2Test(unittest.TestCase):

    def test_production_index_selects_only_delivery_blocker_layering_v3(self):
        result = AUTH.load_and_resolve_current_authority(ROOT)
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(
            result["current_evidence"]["evidence_id"],
            AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
        )
        self.assertEqual(
            result["current_evidence"]["status"],
            "CURRENT_BLOCKED_OFFLINE_BASELINE",
        )
        self.assertEqual(
            result["index_identity"], dict(AUTH.PRODUCTION_INDEX_TRUST_ANCHOR)
        )
        self.assertEqual(len(result["artifact_identities"]), 4)

    def test_production_authority_is_offline_only_and_all_field_gates_are_false(self):
        result = AUTH.load_and_resolve_current_authority(ROOT)
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        for key in (
            "regression_passed", "delivery_ready", "authorizes_field_delivery",
            "formal_tf_pass", "formal_3d_pass", "formal_latency_pass",
            "ros1_noetic_field_install_pass",
            "ros1_noetic_build_install_verified",
        ):
            self.assertFalse(result[key], key)
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertTrue(result["ros1_source_implementation_complete"])
        self.assertEqual(result["ros1_source_architecture_blockers"], [])
        self.assertTrue(
            result["historical_runtime_not_implemented_observation_superseded"]
        )

    def test_old_v2_cannot_be_promoted_to_current_even_with_unchanged_bytes(self):
        index_path = ROOT.joinpath(*Path(AUTH.PRODUCTION_INDEX_RELATIVE_PATH).parts)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["entries"][0]["is_current"] = True
        payload["entries"][0]["lifecycle"] = "CURRENT"
        payload["entries"][0]["status"] = "CURRENT_BLOCKED_OFFLINE_BASELINE"
        payload["entries"][1]["is_current"] = False
        payload["entries"][1]["lifecycle"] = "SUPERSEDED"
        payload["entries"][1]["status"] = "SUPERSEDED_NON_CURRENT"
        payload["current_evidence_id"] = AUTH.SUPERSEDED_REPORT["evidence_id"]
        result = AUTH.validate_formal_admission_evidence_authority_v2(
            ROOT, payload, AUTH.production_generation_spec()
        )
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            item.startswith("formal_authority_v2_top_level_mismatch:")
            or item.startswith("formal_authority_v2_entry_mismatch:")
            for item in result["failures"]
        ), result["failures"])

    def test_production_index_report_and_canonical_identities_are_exact(self):
        spec = AUTH.production_generation_spec()
        self.assertEqual(
            spec["current_report_identity"],
            dict(AUTH.PRODUCTION_CURRENT_REPORT_IDENTITY),
        )
        self.assertEqual(
            spec["canonical_child_identity"],
            dict(AUTH.PRODUCTION_CANONICAL_CHILD_IDENTITY),
        )
        index = json.loads(
            ROOT.joinpath(*Path(AUTH.PRODUCTION_INDEX_RELATIVE_PATH).parts).read_text(
                encoding="utf-8"
            )
        )
        currents = [entry for entry in index["entries"] if entry["is_current"]]
        self.assertEqual(len(currents), 1)
        self.assertEqual(currents[0]["path"], AUTH.PRODUCTION_CURRENT_REPORT_IDENTITY["path"])
        self.assertEqual(index["entries"][0]["status"], "SUPERSEDED_NON_CURRENT")
        self.assertEqual(
            index["predecessor_authority_index"],
            dict(AUTH.PREDECESSOR_INDEX_IDENTITY),
        )

    def test_v2_anchor_cannot_replace_fixed_v3_production_spec(self):
        spec = AUTH.production_generation_spec()
        old_anchor = {
            key: AUTH.PREDECESSOR_INDEX_IDENTITY[key]
            for key in ("path", "size_bytes", "sha256")
        }
        result = AUTH.load_and_resolve_formal_admission_evidence_authority_v2(
            ROOT, spec, old_anchor
        )
        self.assertFalse(result["validated_pass"])
        self.assertFalse(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v2_index_anchor_path_mismatch",
            result["failures"],
        )
        self.assertTrue(result["filename_mtime_selection_forbidden"])

    def test_v2_payload_cannot_validate_against_fixed_v3_production_spec(self):
        old_index_path = ROOT.joinpath(
            *Path(AUTH.PREDECESSOR_INDEX_IDENTITY["path"]).parts
        )
        old_payload = json.loads(old_index_path.read_text(encoding="utf-8"))
        result = AUTH.validate_formal_admission_evidence_authority_v2(
            ROOT, old_payload, AUTH.production_generation_spec()
        )
        self.assertFalse(result["validated_pass"])
        self.assertFalse(
            result["accepted_as_offline_release_selection_authority"]
        )
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            item.startswith("formal_authority_v2_top_level_mismatch:")
            for item in result["failures"]
        ), result["failures"])


if __name__ == "__main__":
    unittest.main()
