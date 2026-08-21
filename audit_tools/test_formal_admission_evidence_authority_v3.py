"""Fail-closed tests for the unactivated successor authority candidate."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit_tools import formal_admission_evidence_authority_v3 as AUTH


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value):
    raw = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _identity(path: Path):
    raw = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


class FormalAdmissionEvidenceAuthorityV3Test(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".authority-v3-test-", dir=ROOT / "audit_tools"
        )
        self.temp_root = Path(self.temporary.name)
        self.spec = AUTH.successor_generation_spec()
        self.payload = AUTH.expected_index_payload(self.spec)

    def tearDown(self):
        self.temporary.cleanup()

    def _candidate_spec(self):
        spec = deepcopy(self.spec)
        spec["index_relative_path"] = (
            self.temp_root / "candidate-index.json"
        ).relative_to(ROOT).as_posix()
        return spec

    def _write_candidate_index(self, spec, payload=None):
        path = ROOT / spec["index_relative_path"]
        _write_json(
            path,
            AUTH.expected_index_payload(spec) if payload is None else payload,
        )
        return _identity(path)

    def _reanchored_report(self, mutation):
        source = ROOT / AUTH.CURRENT_REPORT_IDENTITY["path"]
        report = json.loads(source.read_text(encoding="utf-8"))
        mutation(report)
        path = self.temp_root / "report.json"
        _write_json(path, report)
        spec = deepcopy(self.spec)
        spec["current_report_identity"] = _identity(path)
        return report, spec, AUTH.expected_index_payload(spec)

    def test_real_report_v4_and_canonical_v5_validate_as_offline_only(self):
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, self.payload, self.spec
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["ros1_noetic_build_install_verified"])
        self.assertFalse(result["ros1_noetic_field_install_pass"])
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertFalse(result["formal_tf_pass"])
        self.assertFalse(result["formal_3d_pass"])
        self.assertFalse(result["formal_latency_pass"])

    def test_schema_v3_keeps_family_id_but_has_unique_index_instance(self):
        self.assertEqual(
            self.payload["authority_id"], AUTH.AUTHORITY_FAMILY_ID
        )
        self.assertEqual(
            self.payload["index_instance_id"], AUTH.DEFAULT_INDEX_INSTANCE_ID
        )
        self.assertNotIn(
            "index_instance_id",
            json.loads((ROOT / AUTH.PREDECESSOR_INDEX_IDENTITY["path"]).read_text()),
        )
        currents = [
            item for item in self.payload["entries"] if item["is_current"]
        ]
        self.assertEqual(len(currents), 1)
        self.assertEqual(
            currents[0]["evidence_id"], AUTH.DEFAULT_CURRENT_EVIDENCE_ID
        )
        self.assertEqual(
            self.payload["predecessor_authority_index"]["path"],
            AUTH.PREDECESSOR_INDEX_IDENTITY["path"],
        )

    def test_valid_external_anchor_resolves_temporary_candidate(self):
        spec = self._candidate_spec()
        anchor = self._write_candidate_index(spec)
        result = AUTH.load_and_resolve_formal_admission_evidence_authority_v3(
            ROOT, spec, anchor
        )
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertEqual(
            result["current_evidence"]["evidence_id"],
            AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
        )
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])

    def test_successor_rejects_forged_external_anchor(self):
        anchor = {
            "path": AUTH.SUCCESSOR_INDEX_RELATIVE_PATH,
            "size_bytes": 1,
            "sha256": "0" * 64,
        }
        result = AUTH.load_and_resolve_successor_authority(anchor, ROOT)
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertIsNone(result["current_evidence"])
        self.assertIn(
            "formal_authority_v3_index_size_bytes_mismatch",
            result["failures"],
        )
        self.assertIn(
            "formal_authority_v3_index_sha256_mismatch",
            result["failures"],
        )

    def test_no_argument_production_resolver_tracks_explicit_anchor_state(self):
        result = AUTH.load_and_resolve_current_authority(ROOT)
        if AUTH.PRODUCTION_INDEX_TRUST_ANCHOR is None:
            self.assertFalse(result["validated_pass"])
            self.assertFalse(
                result["accepted_as_offline_release_selection_authority"]
            )
            self.assertFalse(result["production_anchor_configured"])
            self.assertIsNone(result["current_evidence"])
            self.assertIn(
                "formal_authority_v3_production_anchor_not_configured",
                result["failures"],
            )
        else:
            self.assertTrue(result["validated_pass"], result["failures"])
            self.assertTrue(result["production_anchor_configured"])
            self.assertEqual(
                result["current_evidence"]["evidence_id"],
                AUTH.DEFAULT_CURRENT_EVIDENCE_ID,
            )

    def test_external_anchor_path_size_and_hash_are_all_exact(self):
        spec = self._candidate_spec()
        anchor = self._write_candidate_index(spec)
        mutations = (
            ("path", AUTH.SUCCESSOR_INDEX_RELATIVE_PATH),
            ("size_bytes", anchor["size_bytes"] + 1),
            ("sha256", "0" * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                candidate = dict(anchor)
                candidate[key] = value
                result = AUTH.load_and_resolve_formal_admission_evidence_authority_v3(
                    ROOT, spec, candidate
                )
                self.assertFalse(result["validated_pass"])
                self.assertIsNone(result["current_evidence"])

    def test_old_v3_index_payload_cannot_be_promoted(self):
        old = json.loads(
            (ROOT / AUTH.PREDECESSOR_INDEX_IDENTITY["path"]).read_text(
                encoding="utf-8"
            )
        )
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, old, self.spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(any(
            value.startswith("formal_authority_v3_top_level")
            or value.startswith("formal_authority_v3_entry")
            for value in result["failures"]
        ))

    def test_zero_multiple_or_truthy_current_state_fails_closed(self):
        mutations = []
        zero = deepcopy(self.payload)
        zero["entries"][1]["is_current"] = False
        mutations.append(zero)
        multiple = deepcopy(self.payload)
        multiple["entries"][0]["is_current"] = True
        mutations.append(multiple)
        truthy = deepcopy(self.payload)
        truthy["entries"][1]["delivery_ready"] = True
        mutations.append(truthy)
        truthy_gate = deepcopy(self.payload)
        truthy_gate["gate_state"]["authorizes_field_delivery"] = True
        mutations.append(truthy_gate)
        for payload in mutations:
            with self.subTest():
                result = AUTH.validate_formal_admission_evidence_authority_v3(
                    ROOT, payload, self.spec
                )
                self.assertFalse(result["validated_pass"])
                self.assertFalse(result["delivery_ready"])
                self.assertFalse(result["authorizes_field_delivery"])
                self.assertIsNone(result["current_evidence"])

    def test_strict_index_json_rejects_duplicate_key_and_nonfinite(self):
        for raw in (
            b'{"schema_version":"x","schema_version":"y"}\n',
            b'{"value":NaN}\n',
        ):
            with self.subTest(raw=raw):
                spec = self._candidate_spec()
                path = ROOT / spec["index_relative_path"]
                path.write_bytes(raw)
                anchor = _identity(path)
                result = AUTH.load_and_resolve_formal_admission_evidence_authority_v3(
                    ROOT, spec, anchor
                )
                self.assertFalse(result["validated_pass"])
                self.assertIn(
                    "formal_authority_v3_index_strict_json_invalid",
                    result["failures"],
                )
                path.unlink()

    def test_reanchored_summary_count_cannot_replace_ledger_recompute(self):
        def mutate(report):
            report["test_matrix"]["current_generation_collected"] = 143

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "formal_authority_v3_current_report_test_count_mismatch:"
            "current_generation_collected",
            result["failures"],
        )

    def test_pytest_record_omission_with_unchanged_totals_fails(self):
        def mutate(report):
            report["test_matrix"]["pytest_style_file_records"].pop(0)

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "formal_authority_v3_pytest_record_count_invalid",
            result["failures"],
        )

    def test_windows_record_id_marker_and_extra_skip_fail_closed(self):
        def mutate(report):
            record = report["test_matrix"]["unittest_file_records"][0]
            record["record_id"] = "windows:wrong.py"
            record["marker_payload"]["expected_ids"] = []
            host = report["test_matrix"]["unittest_file_records"][3]
            host["skipped_ids"] = [host["expected_ids"][0]]

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertTrue(any(
            "provenance_mismatch" in value
            or "marker_semantic_mismatch" in value
            or "failure_or_unapproved_skip" in value
            for value in result["failures"]
        ))

    def test_wsl_missing_companion_wrong_id_and_executable_drift_fail(self):
        def mutate(report):
            records = report["test_matrix"]["wsl_unittest_file_records"]
            records.pop(
                "ros1_noetic_field_readiness_host_linklike_artifact_posix_companion"
            )
            exact = records[
                "ros1_noetic_field_readiness_exact_cli_posix_companion"
            ]
            exact["record_id"] = "wrong"
            exact["executable"]["version"] = [3, 14, 5]

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "formal_authority_v3_wsl_record_set_invalid",
            result["failures"],
        )

    def test_wsl_ordered_target_manifest_is_host_recomputed(self):
        def mutate(report):
            manifest = report["frozen_inventory"][
                "current_generation_wsl_unittest_target_manifest"
            ]
            manifest["actual_record_ids"] = list(
                reversed(manifest["actual_record_ids"])
            )

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "formal_authority_v3_current_report_wsl_target_manifest_invalid",
            result["failures"],
        )

    def test_composite_raw_copy_and_physical_totals_are_recomputed(self):
        def mutate(report):
            matrix = report["test_matrix"]
            matrix["current_generation_physical_passed"] = 144
            exact = matrix["current_generation_suites"][
                "ros1_noetic_field_readiness_exact_cli"
            ]
            exact["raw_posix_companion"] = deepcopy(exact["raw_windows"])

        unused, spec, payload = self._reanchored_report(mutate)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "formal_authority_v3_current_report_test_count_mismatch:"
            "current_generation_physical_passed",
            result["failures"],
        )
        self.assertIn(
            "formal_authority_v3_exact_suite_material_invalid",
            result["failures"],
        )

    def test_canonical_child_identity_and_live_semantics_are_not_self_reported(self):
        canonical = json.loads(
            (ROOT / AUTH.CANONICAL_CHILD_IDENTITY["path"]).read_text(
                encoding="utf-8"
            )
        )
        canonical["file_count"] += 1
        path = self.temp_root / "canonical.json"
        _write_json(path, canonical)
        spec = deepcopy(self.spec)
        spec["canonical_child_identity"] = _identity(path)
        payload = AUTH.expected_index_payload(spec)
        result = AUTH.validate_formal_admission_evidence_authority_v3(
            ROOT, payload, spec
        )
        self.assertFalse(result["validated_pass"])
        self.assertTrue(any(
            "canonical" in value for value in result["failures"]
        ))

    def test_report_and_canonical_frozen_identities_are_exact(self):
        self.assertEqual(
            AUTH.index_identity(ROOT, AUTH.CURRENT_REPORT_IDENTITY["path"]),
            dict(AUTH.CURRENT_REPORT_IDENTITY),
        )
        self.assertEqual(
            AUTH.index_identity(ROOT, AUTH.CANONICAL_CHILD_IDENTITY["path"]),
            dict(AUTH.CANONICAL_CHILD_IDENTITY),
        )
        self.assertEqual(
            AUTH.index_identity(ROOT, AUTH.PREDECESSOR_INDEX_IDENTITY["path"]),
            {
                key: AUTH.PREDECESSOR_INDEX_IDENTITY[key]
                for key in ("path", "size_bytes", "sha256")
            },
        )


if __name__ == "__main__":
    unittest.main()
