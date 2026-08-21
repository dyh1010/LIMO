import copy
import inspect
import json
import stat
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


import arm_gripper_local_evidence_aggregator as aggregate


TARGET_PATHS = (
    "audit_tools/test_arm_gripper_local_evidence_aggregator.py",
    "audit_tools/test_arm_gripper_local_evidence_generator.py",
    "src/limo_cleanup_executor/test/test_arm_gateway_core.py",
    "src/limo_cleanup_executor/test/test_gripper_gateway_core.py",
)
RUNNER_PATH = "audit_tools/run_unittest_file_tests.py"


def authority_entry(index, disposition="RUNNER_EXECUTED"):
    target_path = TARGET_PATHS[index % len(TARGET_PATHS)]
    case_id = target_path + "::case_{:02d}".format(index)
    if disposition == "RUNNER_EXECUTED":
        execution_kind = "UNITTEST_FILE"
        runner = {
            "path": RUNNER_PATH,
            "schema": "offline_unittest_file_result/v2",
            "kind": "stdlib_unittest_single_file_isolated",
            "mode": "single-file",
            "marker_prefix": "OFFLINE_UNITTEST_FILE_RESULT ",
            "case_results_schema": "offline_case_results/v1",
            "source_sha256": "a" * 64,
        }
        import_roots = ["src/limo_cleanup_executor"]
        expected_skips = []
    else:
        execution_kind = "NOT_EXECUTED_ROS_GRAPH_PROHIBITED"
        runner = None
        import_roots = []
        expected_skips = [{
            "test_id": case_id,
            "reason": "SKIPPED_ROS_GRAPH_PROHIBITED; ROS2_ONLY_ENVIRONMENT",
        }]
    return {
        "suite_id": "suite_{:02d}".format(index),
        "required": True,
        "execution_scope": "PURE_FAKE",
        "targets": [{
            "record_id": "record_{:02d}".format(index),
            "path": target_path,
            "disposition": disposition,
            "execution_kind": execution_kind,
            "runner": runner,
            "import_roots": import_roots,
            "case_ids": [case_id],
            "case_map_sha256": aggregate.canonical_sha256([case_id]),
            "denominator": 1,
        }],
        "expected_denominator": 1,
        "expected_skips": expected_skips,
    }


def authority_source_closure(entries):
    paths = {RUNNER_PATH}
    for entry in entries:
        for target in entry["targets"]:
            paths.add(target["path"])
    return paths


class ArmGripperLocalEvidenceAggregatorContractTest(unittest.TestCase):
    def test_public_aggregate_accepts_only_staging_dir(self):
        parameters = inspect.signature(
            aggregate.aggregate_staging).parameters
        self.assertEqual(list(parameters), ["staging_dir"])
        parser = aggregate._parser()
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertIn("--staging-dir", option_strings)
        for forbidden in (
                "--workspace", "--source-root", "--source-file",
                "--required-suite", "--suite", "--evidence-id"):
            self.assertNotIn(forbidden, option_strings)

    def test_workspace_is_anchored_to_aggregator_repository(self):
        expected = aggregate.Path(aggregate.__file__).resolve().parents[1]
        self.assertEqual(aggregate.WORKSPACE_ROOT, expected)

    def test_aggregator_process_requires_isolated_no_bytecode_python(self):
        valid_flags = types.SimpleNamespace(
            isolated=1, dont_write_bytecode=1, no_user_site=1)
        contract = aggregate.validate_aggregator_process_contract(
            flags=valid_flags,
            environment={},
            executable=aggregate.sys.executable,
        )
        self.assertTrue(contract["isolated"])
        self.assertRegex(contract["executable"]["sha256"], r"^[0-9a-f]{64}$")
        for field in ("isolated", "dont_write_bytecode", "no_user_site"):
            invalid = types.SimpleNamespace(
                isolated=1, dont_write_bytecode=1, no_user_site=1)
            setattr(invalid, field, 0)
            with self.subTest(field=field), self.assertRaisesRegex(
                    aggregate.EvidenceRejected, "requires_python_I_B"):
                aggregate.validate_aggregator_process_contract(
                    flags=invalid,
                    environment={},
                    executable=aggregate.sys.executable,
                )

    def test_aggregator_process_rejects_python_environment_injection(self):
        valid_flags = types.SimpleNamespace(
            isolated=1, dont_write_bytecode=1, no_user_site=1)
        for key in ("PYTHONPATH", "PYTHONHOME"):
            with self.subTest(key=key), self.assertRaisesRegex(
                    aggregate.EvidenceRejected,
                    "aggregator_environment_contaminated"):
                aggregate.validate_aggregator_process_contract(
                    flags=valid_flags,
                    environment={key: "caller-selected"},
                    executable=aggregate.sys.executable,
                )

    def test_strict_json_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "duplicate_json_key:value"):
            aggregate.strict_json_loads(b'{"value":1,"value":2}')

    def test_strict_json_rejects_nonfinite_numbers(self):
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "nonfinite_json_number"):
            aggregate.strict_json_loads(b'{"value":NaN}')

    def test_strict_json_rejects_invalid_utf8(self):
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "not_utf8"):
            aggregate.strict_json_loads(b'{"value":"\xff"}')

    def test_exact_marker_accepts_canonical_native_line(self):
        payload = {"result": "PASS", "value": "本地"}
        prefix = "OFFLINE_TEST_RESULT "
        raw = (
            prefix.encode("ascii")
            + aggregate.runner_json_bytes(payload)
            + b"\n")
        parsed, identity = aggregate.parse_exact_marker(raw, prefix)
        self.assertEqual(parsed, payload)
        self.assertEqual(
            identity["line_ending_hex"], "0a")

    def test_exact_marker_rejects_replaced_line_ending(self):
        payload = aggregate.runner_json_bytes({"result": "PASS"})
        raw = b"OFFLINE_TEST_RESULT " + payload + b"\r\n"
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "unexpected_cr"):
            aggregate.parse_exact_marker(raw, "OFFLINE_TEST_RESULT ")

    def test_exact_marker_rejects_extra_line_or_marker(self):
        line = (
            b"OFFLINE_TEST_RESULT "
            + aggregate.runner_json_bytes({"result": "PASS"})
            + b"\n")
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "fixed_lf_contract_invalid"):
            aggregate.parse_exact_marker(
                line + line, "OFFLINE_TEST_RESULT ")

    def test_exact_marker_rejects_noncanonical_json_payload(self):
        raw = (
            b"OFFLINE_TEST_RESULT {\"z\": 1, \"a\": 2}"
            + b"\n")
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "payload_not_canonical"):
            aggregate.parse_exact_marker(raw, "OFFLINE_TEST_RESULT ")

    def test_reparse_attribute_is_linklike(self):
        info = types.SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_file_attributes=getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        )
        self.assertTrue(aggregate._is_linklike("unused", info))

    def test_windows_junction_probe_is_linklike(self):
        info = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        with mock.patch.object(aggregate.os.path, "isjunction", return_value=True):
            self.assertTrue(aggregate._is_linklike("unused", info))

    def test_staging_inventory_is_exact_sorted_raw_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            (root / "raw" / "b.stderr.bin").write_bytes(b"stderr")
            (root / "a.json").write_bytes(b"{}\n")
            inventory = aggregate.read_staging_inventory(root)
        self.assertEqual(
            [item["path"] for item in inventory],
            ["a.json", "raw/b.stderr.bin"],
        )
        self.assertEqual(
            aggregate.validate_exact_inventory(inventory, copy.deepcopy(
                inventory)),
            inventory,
        )

    def test_staging_inventory_rejects_missing_extra_and_permutation(self):
        expected = [
            {"path": "a", "size_bytes": 1, "sha256": "a" * 64},
            {"path": "b", "size_bytes": 1, "sha256": "b" * 64},
        ]
        mutations = (
            expected[:-1],
            expected + [{
                "path": "c", "size_bytes": 1, "sha256": "c" * 64}],
            list(reversed(expected)),
        )
        for actual in mutations:
            with self.subTest(actual=actual), self.assertRaises(
                    aggregate.EvidenceRejected):
                aggregate.validate_exact_inventory(actual, expected)

    def test_canonical_relative_rejects_traversal_absolute_and_backslash(self):
        for value in ("../escape", "/absolute", "a\\b", "a/../b"):
            with self.subTest(value=value), self.assertRaises(
                    aggregate.EvidenceRejected):
                aggregate._canonical_relative(value, "path")

    def test_source_closure_rejects_caller_selected_subset(self):
        frozen = tuple(sorted(aggregate.MINIMUM_REQUIRED_SOURCE_PATHS))
        with mock.patch.object(
                aggregate, "EXPECTED_SOURCE_CLOSURE", frozen):
            with self.assertRaisesRegex(
                    aggregate.EvidenceRejected,
                    "source_closure_not_exact_frozen_scope"):
                aggregate._validate_source_closure(frozen[1:])

    def test_source_closure_rejects_extra_order_permutation(self):
        paths = sorted(aggregate.MINIMUM_REQUIRED_SOURCE_PATHS)
        with mock.patch.object(
                aggregate, "EXPECTED_SOURCE_CLOSURE", tuple(paths)):
            permuted = list(paths)
            permuted[0], permuted[1] = permuted[1], permuted[0]
            with self.assertRaisesRegex(
                    aggregate.EvidenceRejected, "source_closure_not_sorted"):
                aggregate._validate_source_closure(permuted)

            extra = sorted(paths + [
                "src/limo_cleanup_executor/test/test_arm_backends.py"])
            with self.assertRaisesRegex(
                    aggregate.EvidenceRejected,
                    "source_closure_not_exact_frozen_scope"):
                aggregate._validate_source_closure(extra)

    def test_source_closure_accepts_only_exact_frozen_scope(self):
        paths = tuple(sorted(aggregate.MINIMUM_REQUIRED_SOURCE_PATHS))
        with mock.patch.object(
                aggregate, "EXPECTED_SOURCE_CLOSURE", paths):
            self.assertEqual(
                aggregate._validate_source_closure(list(paths)), paths)

    def test_suite_authority_requires_exactly_four_suites(self):
        for count in (3, 5):
            entries = [authority_entry(index) for index in range(count)]
            with self.subTest(count=count), self.assertRaisesRegex(
                    aggregate.EvidenceRejected, "exactly_four"):
                aggregate._validate_suite_authority(
                    entries, authority_source_closure(entries))

    def test_suite_authority_rejects_synthetic_missing_case_map(self):
        entries = [authority_entry(index) for index in range(4)]
        entries[0]["targets"][0]["case_ids"] = []
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "case_map_invalid"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_extra_or_duplicate_case(self):
        entries = [authority_entry(index) for index in range(4)]
        target = entries[0]["targets"][0]
        case_id = target["path"] + "::same"
        target["case_ids"] = [case_id, case_id]
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "case_map_invalid"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_suite_permutation(self):
        entries = [authority_entry(index) for index in range(4)]
        entries[0], entries[1] = entries[1], entries[0]
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "not_sorted_unique"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_unknown_extra_keys(self):
        entries = [authority_entry(index) for index in range(4)]
        entries[0]["caller_selected"] = True
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "entry_not_object"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_case_not_bound_to_target_path(self):
        entries = [authority_entry(index) for index in range(4)]
        target = entries[0]["targets"][0]
        target["case_ids"] = ["synthetic::case"]
        target["case_map_sha256"] = aggregate.canonical_sha256(
            target["case_ids"])
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "case_map_invalid"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_target_reuse_across_suites(self):
        entries = [authority_entry(index) for index in range(4)]
        duplicate = copy.deepcopy(entries[0]["targets"][0])
        duplicate["record_id"] = "record_01"
        entries[1]["targets"] = [duplicate]
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "target_reused"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_suite_authority_rejects_runner_on_nonexecuted_smoke(self):
        entries = [authority_entry(index) for index in range(4)]
        smoke = authority_entry(
            2, "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED")
        smoke["targets"][0]["runner"] = copy.deepcopy(
            entries[0]["targets"][0]["runner"])
        entries[2] = smoke
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "nonexecuted_target_has_runner"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_nonexecuted_smoke_must_be_an_exact_expected_skip(self):
        entries = [authority_entry(index) for index in range(4)]
        entries[2] = authority_entry(
            2, "STATIC_AST_NOT_EXECUTED_ROS_GRAPH_PROHIBITED")
        entries[2]["expected_skips"] = []
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected,
                "static_nonexecuted_case_not_expected_skip"):
            aggregate._validate_suite_authority(
                entries, authority_source_closure(entries))

    def test_valid_exact_target_level_authority_is_deep_copied(self):
        entries = [authority_entry(index) for index in range(4)]
        validated = aggregate._validate_suite_authority(
            entries, authority_source_closure(entries))
        self.assertEqual(len(validated), 4)
        entries[0]["targets"][0]["record_id"] = "mutated"
        self.assertEqual(
            validated[0]["targets"][0]["record_id"], "record_00")

    def test_runner_source_sha_is_mechanically_bound_to_closure(self):
        entries = [authority_entry(index) for index in range(4)]
        closure = sorted(authority_source_closure(entries))
        authority = {
            "source_closure": tuple(closure),
            "suite_authority": aggregate._validate_suite_authority(
                entries, set(closure)),
        }
        source_identity = {
            "files": [
                {
                    "path": path,
                    "size_bytes": 1,
                    "sha256": "a" * 64 if path == RUNNER_PATH else "b" * 64,
                }
                for path in closure
            ],
        }
        self.assertTrue(aggregate.validate_authority_source_bindings(
            authority, source_identity))
        replaced = copy.deepcopy(authority)
        replaced["suite_authority"][0]["targets"][0]["runner"][
            "source_sha256"] = "c" * 64
        with self.assertRaisesRegex(
                aggregate.EvidenceRejected, "runner_source_sha256_mismatch"):
            aggregate.validate_authority_source_bindings(
                replaced, source_identity)

    def test_fixed_truth_never_authorizes_delivery_or_backend(self):
        truth = aggregate._fixed_blocked_truth()
        self.assertEqual(truth["runtime_baseline"], "ROS1_NOETIC")
        self.assertEqual(
            truth["wrapper_runtime_status"],
            "ROS2_FOXY_OFFLINE_LEGACY_ONLY",
        )
        self.assertEqual(truth["ros1_adapter"], "BLOCKED_MISSING")
        self.assertEqual(truth["readiness"], "BLOCKED")
        self.assertEqual(
            truth["real_backend"],
            {"arm": "BLOCKED", "gripper": "BLOCKED"},
        )
        for key in ("release", "field", "delivery", "hardware"):
            self.assertIs(truth[key], False)
        self.assertIn("NO_EXTERNAL_SIGNATURE", truth["local_hash_authority"])

    def test_rejection_is_not_current_evidence_and_hash_self_verifies(self):
        report = aggregate._rejection_report("synthetic_rejected", "staging")
        self.assertEqual(report["evidence_status"], "REJECTED_NOT_EVIDENCE")
        self.assertFalse(report["input_accepted"])
        self.assertEqual(report["readiness"], "BLOCKED")
        self.assertEqual(
            report["evidence_sha256"], aggregate.evidence_sha256(report))
        changed = copy.deepcopy(report)
        changed["release"] = True
        self.assertNotEqual(
            report["evidence_sha256"], aggregate.evidence_sha256(changed))

    def test_stale_status_pattern_covers_historical_report_status(self):
        self.assertIsNotNone(
            aggregate._STALE_RE.search("STALE_NOT_RELEASE_EVIDENCE"))
        self.assertIsNotNone(aggregate._STALE_RE.search("SUPERSEDED"))

    def test_evidence_id_is_exact_source_prefix_and_full_material_hash(self):
        source_sha = "1" * 64
        material_sha = aggregate.material_sha256({"suite_count": 4})
        evidence_id = aggregate.derive_evidence_id(
            source_sha, material_sha)
        self.assertEqual(
            evidence_id,
            "ARM_GRIPPER_LOCAL_V3_{}_{}".format(
                source_sha[:16], material_sha),
        )
        self.assertEqual(
            aggregate.validate_evidence_id(
                evidence_id, source_sha, material_sha),
            evidence_id,
        )

    def test_old_or_synthetic_evidence_id_is_rejected(self):
        source_sha = "2" * 64
        material_sha = "3" * 64
        for evidence_id in (
                "arm_gripper_local_safety_20260814",
                "ARM_GRIPPER_LOCAL_V3_20260817T120000Z_deadbeef",
                "ARM_GRIPPER_LOCAL_V3_{}_{}".format(
                    "4" * 16, material_sha),
                "ARM_GRIPPER_LOCAL_V3_{}_{}".format(
                    source_sha[:16], "5" * 64)):
            with self.subTest(evidence_id=evidence_id), self.assertRaisesRegex(
                    aggregate.EvidenceRejected, "not_exact_material"):
                aggregate.validate_evidence_id(
                    evidence_id, source_sha, material_sha)

    def test_cli_missing_policy_fails_closed_without_current_evidence(self):
        stdout = mock.patch("sys.stdout")
        with mock.patch.object(
                aggregate, "validate_aggregator_process_contract",
                return_value={"executable": {}}), mock.patch.object(
                    aggregate, "aggregate_staging",
                    side_effect=aggregate.EvidenceRejected(
                        "policy_api_missing")):
            with stdout as stream:
                status = aggregate.main(["--staging-dir", "missing"])
        self.assertEqual(status, 2)
        rendered = "".join(call.args[0] for call in stream.write.call_args_list)
        report = json.loads(rendered)
        self.assertEqual(report["evidence_status"], "REJECTED_NOT_EVIDENCE")
        self.assertFalse(report["release"])

    def test_main_cannot_bypass_process_contract(self):
        with mock.patch.object(
                aggregate, "validate_aggregator_process_contract",
                side_effect=aggregate.EvidenceRejected(
                    "aggregator_requires_python_I_B")), mock.patch.object(
                        aggregate, "aggregate_staging") as staged, mock.patch(
                            "sys.stdout"):
            status = aggregate.main(["--staging-dir", "synthetic"])
        self.assertEqual(status, 2)
        staged.assert_not_called()


if __name__ == "__main__":
    unittest.main()
