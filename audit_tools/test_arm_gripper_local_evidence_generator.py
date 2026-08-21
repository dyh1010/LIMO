import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import arm_gripper_local_evidence_generator as generator


def identity(path, payload=b"x"):
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class ArmGripperLocalEvidenceGeneratorContractTest(unittest.TestCase):
    def test_authority_surface_is_exactly_twenty_three_targets(self):
        self.assertEqual(len(generator.FIXED_TARGET_PATHS), 23)
        self.assertEqual(len(generator.ROS_SMOKE_PATHS), 2)
        self.assertTrue(generator.ROS_SMOKE_PATHS <= generator.FIXED_TARGET_PATHS)
        self.assertEqual(
            generator.FIXED_RUNNERS,
            {
                "UNITTEST_FILE": "audit_tools/run_unittest_file_tests.py",
                "PYTEST_STYLE_FILE": "audit_tools/run_pytest_style_tests.py",
                "STATIC_AUDIT_JSON":
                    "audit_tools/arm_gripper_local_static_audit.py",
            },
        )

    def test_cli_rejects_caller_selected_suite_source_runner_and_output(self):
        options = {
            value
            for action in generator._parser()._actions
            for value in action.option_strings
        }
        self.assertEqual(
            options - {"-h", "--help"},
            {"--staging-dir", "--reservation-token"},
        )
        for forbidden in (
                "--suite", "--target", "--runner", "--source",
                "--workspace", "--output", "--evidence-id"):
            self.assertNotIn(forbidden, options)

    def test_process_contract_requires_I_S_B_and_clean_python_environment(self):
        good = types.SimpleNamespace(
            isolated=1, no_site=1, no_user_site=1, dont_write_bytecode=1)
        generator._validate_process_contract(good, {})
        for field in ("isolated", "no_site", "no_user_site",
                      "dont_write_bytecode"):
            values = vars(good).copy()
            values[field] = 0
            with self.subTest(field=field), self.assertRaisesRegex(
                    generator.GenerationRejected, "requires_python_I_S_B"):
                generator._validate_process_contract(
                    types.SimpleNamespace(**values), {})
        for key in ("PYTHONHOME", "PYTHONPATH"):
            with self.subTest(key=key), self.assertRaisesRegex(
                    generator.GenerationRejected, "environment_contaminated"):
                generator._validate_process_contract(good, {key: "forged"})

    def test_execution_binding_exactly_binds_generator_and_bootstrap(self):
        current = identity(generator.GENERATOR_RELATIVE_PATH)
        policy = {"producer_contract": {"bootstrap_sha256": "a" * 64}}
        binding = {
            "schema_version": generator.EXECUTION_COMPONENT_BINDING_SCHEMA,
            "component_kind": generator.EXECUTION_COMPONENT_KIND,
            "path": generator.GENERATOR_RELATIVE_PATH,
            "size_bytes": current["size_bytes"],
            "sha256": current["sha256"],
            "bootstrap_sha256": "a" * 64,
        }
        with mock.patch.object(
                generator, "_workspace_file",
                return_value=(Path("generator.py"), (b"x", current))):
            self.assertEqual(
                generator._validate_execution_component_binding(
                    policy, binding), current)
            changed = dict(binding)
            changed["sha256"] = "b" * 64
            with self.assertRaisesRegex(
                    generator.GenerationRejected, "binding_mismatch"):
                generator._validate_execution_component_binding(
                    policy, changed)

    def test_runner_commands_use_same_fd_bootstrap_and_static_exact_argv(self):
        runner = {
            "path": generator.STATIC_RUNNER,
            "source_sha256": "c" * 64,
        }
        static = generator._fixed_runner_command(
            {"execution_kind": "STATIC_AUDIT_JSON"}, runner)
        self.assertEqual(static[1:4], ["-I", "-S", "-B"])
        self.assertEqual(static[-2:], ["--workspace", str(generator.WORKSPACE_ROOT)])
        for forbidden in ("--target", "--expected-id", "--import-root"):
            self.assertNotIn(forbidden, static)

        target = {
            "execution_kind": "UNITTEST_FILE",
            "path": "test/example.py",
            "import_roots": ["src/example"],
            "case_ids": ["test/example.py::Case.test_one"],
        }
        runner = {
            "path": generator.UNITTEST_RUNNER,
            "source_sha256": "d" * 64,
        }
        command = generator._fixed_runner_command(target, runner)
        self.assertIn("--target", command)
        self.assertIn("--expected-id", command)
        self.assertIn(generator.SAME_FD_BOOTSTRAP, command)

    def test_marker_parser_requires_one_canonical_utf8_lf_record(self):
        payload = {"result": "PASS", "测试": True}
        raw = (b"OFFLINE_TEST_RESULT "
               + generator.canonical_json_bytes(payload) + b"\n")
        parsed, digest = generator._parse_marker(
            raw, "OFFLINE_TEST_RESULT ")
        self.assertEqual(parsed, payload)
        self.assertEqual(
            digest,
            hashlib.sha256(generator.canonical_json_bytes(payload)).hexdigest())
        for bad in (raw + raw, raw.replace(b"\n", b"\r\n")):
            with self.subTest(raw=bad), self.assertRaises(
                    generator.GenerationRejected):
                generator._parse_marker(bad, "OFFLINE_TEST_RESULT ")

    def test_ros_smoke_inventory_is_ast_only_and_never_imported(self):
        source = (
            "import module_that_must_not_be_imported\n"
            "class Smoke:\n"
            "    def test_z(self): pass\n"
            "    def test_a(self): pass\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smoke.py"
            path.write_bytes(source)
            self.assertEqual(
                generator._ast_case_ids(path, "test/smoke.py"),
                [
                    "test/smoke.py::Smoke.test_a",
                    "test/smoke.py::Smoke.test_z",
                ],
            )

    def test_case_results_bind_exact_outcome_and_skip_reason(self):
        test_id = "test/example.py::Case.test_one"
        with self.assertRaisesRegex(
                generator.GenerationRejected, "unexpected_nonpass_case"):
            generator._validate_case_results(
                [{"test_id": test_id, "outcome": "skipped",
                  "reason": "caller-selected"}], [test_id], {})
        reason = "SKIPPED_ROS_GRAPH_PROHIBITED; ROS2_ONLY_ENVIRONMENT"
        self.assertEqual(
            generator._validate_case_results(
                [{"test_id": test_id, "outcome": "skipped",
                  "reason": reason}], [test_id], {test_id: reason}),
            {"passed": 0, "failed": 0, "skipped": 1},
        )

    def test_runner_loaded_bytes_reject_target_aba_and_unbound_source(self):
        target = identity("test/target.py", b"target")
        runner = identity("audit_tools/runner.py", b"runner")
        source = {"files": [target, runner]}
        payload = {
            "runner_identity_before": runner,
            "runner_identity_after": runner,
            "path": target["path"],
            "sha256": target["sha256"],
            "workspace_loader_guard_restored": True,
            "workspace_pyc_inventory_stable": True,
            "workspace_pyc_bytes_read": 0,
            "workspace_source_reads": [runner, target],
        }
        payload["workspace_source_reads"].sort(key=lambda item: item["path"])
        generator._validate_runner_loaded_bytes(
            payload, target["path"], target, runner["path"], runner, source)
        changed = json.loads(json.dumps(payload))
        changed["workspace_source_reads"][1]["sha256"] = "e" * 64
        with self.assertRaisesRegex(
                generator.GenerationRejected, "source_read_not_bound"):
            generator._validate_runner_loaded_bytes(
                changed, target["path"], target,
                runner["path"], runner, source)

    def test_static_scope_must_equal_exact_source_identity_map(self):
        first = identity("a.py", b"a")
        second = identity("b.py", b"b")
        source = {"files": [first, second]}
        payload = {"scope": {
            "files": 2,
            "sha256": {"a.py": first["sha256"], "b.py": second["sha256"]},
        }}
        generator._validate_static_scope(payload, source)
        payload["scope"]["sha256"]["extra.py"] = "f" * 64
        with self.assertRaisesRegex(
                generator.GenerationRejected, "scope_not_exact"):
            generator._validate_static_scope(payload, source)


if __name__ == "__main__":
    unittest.main()
