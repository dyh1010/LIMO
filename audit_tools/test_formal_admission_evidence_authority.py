"""Fail-closed tests for the ROS1 formal-admission generation authority."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from audit_tools import formal_admission_evidence_authority as AUTH


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / AUTH.INDEX_RELATIVE_PATH


def payload():
    return json.loads(INDEX.read_text(encoding="utf-8"))


def copy_minimal_workspace(destination):
    destination = Path(destination)
    paths = [
        AUTH.INDEX_RELATIVE_PATH.as_posix(),
        AUTH.PREDECESSOR_INDEX_RELATIVE_PATH,
        AUTH.PREDECESSOR_REPORT_RELATIVE_PATH,
        AUTH.CURRENT_REPORT_RELATIVE_PATH,
        AUTH.CANONICAL_CHILD_RELATIVE_PATH,
    ]
    canonical = json.loads(
        (ROOT / AUTH.CANONICAL_CHILD_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    paths.extend(
        canonical["canonical_source_root"] + "/" + item["path"]
        for item in canonical["entries"]
    )
    for relative in paths:
        source = ROOT.joinpath(*Path(relative).parts)
        target = destination.joinpath(*Path(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
    return destination


class FormalAdmissionEvidenceAuthorityTest(unittest.TestCase):

    def assert_failed(self, result, prefix):
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertIsNone(result["current_evidence"])
        self.assertTrue(
            any(item.startswith(prefix) for item in result["failures"]),
            result["failures"],
        )

    def validate(self, value):
        return AUTH.validate_formal_admission_evidence_authority(ROOT, value)

    def test_canonical_index_selects_one_blocked_current_and_child(self):
        result = AUTH.load_and_resolve_formal_admission_evidence_authority()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(
            result["current_evidence"]["evidence_id"], AUTH.CURRENT_EVIDENCE_ID
        )
        self.assertEqual(result["current_evidence"]["status"], AUTH.CURRENT_STATUS)
        self.assertEqual(len(result["artifact_identities"]), 4)
        self.assertEqual(result["index_identity"], dict(AUTH.INDEX_TRUST_ANCHOR))

    def test_authority_pass_never_becomes_formal_field_or_delivery_pass(self):
        result = AUTH.load_and_resolve_formal_admission_evidence_authority()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertTrue(result["accepted_as_offline_release_selection_authority"])
        self.assertFalse(result["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(result["regression_passed"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertFalse(result["formal_tf_pass"])
        self.assertFalse(result["formal_3d_pass"])
        self.assertFalse(result["ros1_noetic_field_install_pass"])

    def test_missing_or_extra_top_level_state_fails_closed(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                value = payload()
                if mutation == "missing":
                    value.pop("generation_scope")
                else:
                    value["mtime"] = 0
                self.assert_failed(
                    self.validate(value), "formal_authority_top_level_keys_invalid"
                )

    def test_zero_or_multiple_current_fails_closed(self):
        zero = payload()
        zero["entries"][1]["is_current"] = False
        self.assert_failed(
            self.validate(zero), "formal_authority_current_count_invalid"
        )
        multiple = payload()
        multiple["entries"][0]["is_current"] = True
        self.assert_failed(
            self.validate(multiple), "formal_authority_current_count_invalid"
        )

    def test_path_size_hash_and_status_mismatch_fails_closed(self):
        for key, value in (
            ("path", AUTH.PREDECESSOR_REPORT_RELATIVE_PATH),
            ("size_bytes", 318600),
            ("sha256", "0" * 64),
            ("status", "CURRENT"),
        ):
            with self.subTest(key=key):
                mutated = payload()
                mutated["entries"][1][key] = value
                self.assert_failed(
                    self.validate(mutated),
                    "formal_authority_entry_mismatch:" + AUTH.CURRENT_EVIDENCE_ID,
                )

    def test_wrong_generation_scope_and_filename_mtime_policy_fail_closed(self):
        for key, value in (
            ("generation_scope", "field_delivery"),
            ("filename_mtime_selection_forbidden", False),
            ("uses_filename_or_mtime_authority", True),
            ("selection_authority", "NEWEST_MTIME"),
        ):
            with self.subTest(key=key):
                mutated = payload()
                mutated[key] = value
                self.assert_failed(
                    self.validate(mutated),
                    "formal_authority_top_level_mismatch:" + key,
                )

    def test_extra_or_duplicate_entry_fails_closed(self):
        extra = payload()
        extra["entries"].append(deepcopy(extra["entries"][0]))
        extra["entries"][-1]["evidence_id"] = "extra"
        self.assert_failed(extra_result := self.validate(extra), "formal_authority_entry_count_invalid")
        self.assertFalse(extra_result["delivery_ready"])
        duplicate = payload()
        duplicate["entries"][1]["evidence_id"] = duplicate["entries"][0]["evidence_id"]
        self.assert_failed(
            self.validate(duplicate), "formal_authority_duplicate_evidence_id"
        )

    def test_child_path_role_parent_and_hash_are_exact(self):
        for key, value in (
            ("path", AUTH.CURRENT_REPORT_RELATIVE_PATH),
            ("role", "field_evidence"),
            ("parent_evidence_id", AUTH.PREDECESSOR_EVIDENCE_ID),
            ("sha256", "f" * 64),
        ):
            with self.subTest(key=key):
                mutated = payload()
                mutated["child_artifacts"][0][key] = value
                self.assert_failed(
                    self.validate(mutated), "formal_authority_child_artifacts_invalid"
                )

    def test_truthy_regression_field_or_delivery_claim_fails_closed(self):
        mutations = (
            ("top", "authorizes_field_delivery"),
            ("entry", "delivery_ready"),
            ("entry", "regression_passed"),
            ("entry", "authorizes_field_delivery"),
            ("gate", "delivery_ready"),
            ("gate", "formal_tf_pass"),
            ("gate", "formal_3d_pass"),
            ("gate", "ros1_noetic_field_install_pass"),
        )
        for scope, key in mutations:
            with self.subTest(scope=scope, key=key):
                mutated = payload()
                if scope == "top":
                    mutated[key] = True
                    prefix = "formal_authority_top_level_mismatch:" + key
                elif scope == "entry":
                    mutated["entries"][1][key] = True
                    prefix = "formal_authority_entry_mismatch:" + AUTH.CURRENT_EVIDENCE_ID
                else:
                    mutated["gate_state"][key] = True
                    prefix = "formal_authority_top_level_mismatch:gate_state"
                self.assert_failed(self.validate(mutated), prefix)

    def test_boolean_fields_reject_integer_aliases(self):
        mutations = (
            ("entries", 0, "is_current", 0),
            ("entries", 1, "delivery_ready", 0),
            ("child_artifacts", 0, "authorizes_field_delivery", 0),
            ("gate_state", None, "formal_tf_pass", 0),
        )
        for section, index, key, value in mutations:
            with self.subTest(section=section, key=key):
                mutated = payload()
                target = mutated[section] if index is None else mutated[section][index]
                target[key] = value
                result = self.validate(mutated)
                self.assertFalse(result["validated_pass"], result)
                self.assertFalse(result["delivery_ready"])
                self.assertFalse(result["authorizes_field_delivery"])

    def test_current_report_bytes_or_semantics_cannot_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = copy_minimal_workspace(directory)
            report = root / AUTH.CURRENT_REPORT_RELATIVE_PATH
            report.write_bytes(report.read_bytes() + b" ")
            self.assert_failed(
                AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                "formal_authority_artifact_size_mismatch:" + AUTH.CURRENT_EVIDENCE_ID,
            )
        current = json.loads((ROOT / AUTH.CURRENT_REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
        current["delivery_ready"] = True
        failures = AUTH._validate_frozen_report(current, current=True)
        self.assertIn("current_report_semantic_mismatch:delivery_ready", failures)

    def test_canonical_child_bytes_or_semantics_cannot_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = copy_minimal_workspace(directory)
            child = root / AUTH.CANONICAL_CHILD_RELATIVE_PATH
            child.write_bytes(child.read_bytes() + b" ")
            self.assert_failed(
                AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                "formal_authority_artifact_size_mismatch:ros1_noetic_canonical_source_admission_20260815_v2",
            )
        canonical = json.loads((ROOT / AUTH.CANONICAL_CHILD_RELATIVE_PATH).read_text(encoding="utf-8"))
        canonical["source_contract_pass"] = True
        failures = AUTH._validate_canonical_child(canonical, ROOT)
        self.assertIn("canonical_child_semantic_mismatch:source_contract_pass", failures)

    def test_predecessor_report_or_old_authority_drift_fails_closed(self):
        for relative, artifact_id in (
            (AUTH.PREDECESSOR_REPORT_RELATIVE_PATH, AUTH.PREDECESSOR_EVIDENCE_ID),
            (AUTH.PREDECESSOR_INDEX_RELATIVE_PATH, "predecessor_index"),
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = copy_minimal_workspace(directory)
                target = root / relative
                target.write_bytes(target.read_bytes() + b" ")
                self.assert_failed(
                    AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                    "formal_authority_artifact_size_mismatch:" + artifact_id,
                )

    def test_index_external_size_and_hash_anchor_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = copy_minimal_workspace(directory)
            target = root / AUTH.INDEX_RELATIVE_PATH
            target.write_bytes(target.read_bytes() + b" ")
            result = AUTH.load_and_resolve_formal_admission_evidence_authority(root)
            self.assert_failed(result, "formal_authority_index_size_mismatch")
            self.assertIn("formal_authority_index_sha256_mismatch", result["failures"])

    def test_duplicate_key_and_nonfinite_index_json_fail_closed(self):
        cases = (
            b'{"schema_version":1,"schema_version":1}',
            b'{"value":NaN}',
        )
        for raw in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                root = copy_minimal_workspace(directory)
                (root / AUTH.INDEX_RELATIVE_PATH).write_bytes(raw)
                self.assert_failed(
                    AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                    "formal_authority_index_strict_json_invalid",
                )

    def test_live_canonical_source_hash_drift_fails_even_when_manifest_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = copy_minimal_workspace(directory)
            canonical = json.loads((root / AUTH.CANONICAL_CHILD_RELATIVE_PATH).read_text(encoding="utf-8"))
            source = root / canonical["canonical_source_root"] / canonical["entries"][0]["path"]
            source.write_bytes(source.read_bytes() + b" ")
            self.assert_failed(
                AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                "canonical_child_live_source_identity_mismatch:",
            )

    def test_linklike_or_nonregular_bound_artifact_fails_closed(self):
        original = AUTH._is_linklike

        def linked(path):
            if Path(path).name == Path(AUTH.CURRENT_REPORT_RELATIVE_PATH).name:
                return True
            return original(Path(path))

        with mock.patch.object(AUTH, "_is_linklike", side_effect=linked):
            self.assert_failed(
                AUTH.load_and_resolve_formal_admission_evidence_authority(),
                "formal_authority_artifact_unreadable:" + AUTH.CURRENT_EVIDENCE_ID,
            )
        with tempfile.TemporaryDirectory() as directory:
            root = copy_minimal_workspace(directory)
            target = root / AUTH.CURRENT_REPORT_RELATIVE_PATH
            target.unlink()
            target.mkdir()
            self.assert_failed(
                AUTH.load_and_resolve_formal_admission_evidence_authority(root),
                "formal_authority_artifact_unreadable:" + AUTH.CURRENT_EVIDENCE_ID,
            )


if __name__ == "__main__":
    unittest.main()
