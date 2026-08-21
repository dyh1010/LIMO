"""Tests for the non-formal runner diagnostic lineage sidecar."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from audit_tools import runner_platform_diagnostic_lineage as LINEAGE


ROOT = Path(__file__).resolve().parents[1]


class RunnerPlatformDiagnosticLineageTest(unittest.TestCase):

    def assert_failed(self, payload, code):
        result = LINEAGE.validate_runner_diagnostic_lineage(payload, ROOT)
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertFalse(result["accepted_by_formal_evidence_consumer"])
        self.assertIn(code, result["failures"])

    def test_real_sidecar_binds_unselected_diagnostic_and_v4_authority(self):
        result = LINEAGE.load_and_validate_runner_diagnostic_lineage()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(result["diagnostic_status"], "NON_FORMAL_UNSELECTED")
        self.assertFalse(result["diagnostic_may_be_formal_predecessor"])
        self.assertEqual(
            result["current_formal_authority_index_id"],
            LINEAGE.AUTHORITY_INDEX_ID,
        )
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)

    def test_missing_or_wrong_diagnostic_identity_fails_closed(self):
        missing = deepcopy(LINEAGE.expected_sidecar_payload())
        missing["diagnostic_artifact"].pop("sha256")
        self.assert_failed(missing, "runner_diagnostic_lineage_payload_mismatch")
        wrong = deepcopy(LINEAGE.expected_sidecar_payload())
        wrong["diagnostic_artifact"]["size_bytes"] += 1
        self.assert_failed(wrong, "runner_diagnostic_lineage_payload_mismatch")

    def test_wrong_current_authority_fails_closed(self):
        for key, value in (
            ("index_instance_id", "old-v1"),
            ("path", LINEAGE.DIAGNOSTIC_RELATIVE_PATH.as_posix()),
            ("sha256", "0" * 64),
        ):
            with self.subTest(key=key):
                payload = deepcopy(LINEAGE.expected_sidecar_payload())
                payload["current_formal_authority"][key] = value
                self.assert_failed(
                    payload, "runner_diagnostic_lineage_payload_mismatch"
                )

    def test_diagnostic_cannot_be_current_formal_or_delivery_authority(self):
        mutations = (
            ("is_current", True),
            ("authorizes_field_delivery", True),
            ("accepted_by_formal_evidence_consumer", True),
            ("may_be_formal_predecessor", True),
            ("status", "CURRENT_BLOCKED_OFFLINE_BASELINE"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                payload = deepcopy(LINEAGE.expected_sidecar_payload())
                payload["diagnostic_artifact"][key] = value
                self.assert_failed(
                    payload, "runner_diagnostic_lineage_payload_mismatch"
                )

    def test_top_level_formal_or_delivery_escalation_fails_closed(self):
        for key in (
            "authorizes_field_delivery",
            "accepted_by_formal_evidence_consumer",
            "delivery_ready",
            "formal_tf_pass",
            "formal_3d_pass",
            "formal_latency_pass",
        ):
            with self.subTest(key=key):
                payload = deepcopy(LINEAGE.expected_sidecar_payload())
                payload[key] = True
                self.assert_failed(
                    payload, "runner_diagnostic_lineage_payload_mismatch"
                )

    def test_filename_or_mtime_selection_is_forbidden(self):
        for key, value in (
            ("filename_mtime_selection_forbidden", False),
            ("uses_filename_or_mtime_authority", True),
            ("selection_authority", "NEWEST_MTIME"),
        ):
            with self.subTest(key=key):
                payload = deepcopy(LINEAGE.expected_sidecar_payload())
                payload[key] = value
                self.assert_failed(
                    payload, "runner_diagnostic_lineage_payload_mismatch"
                )

    def test_live_frozen_diagnostic_overwrite_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                LINEAGE.SIDECAR_RELATIVE_PATH,
                LINEAGE.DIAGNOSTIC_RELATIVE_PATH,
                LINEAGE.AUTHORITY_RELATIVE_PATH,
            ):
                target = root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT.joinpath(*relative.parts), target)
            diagnostic = root.joinpath(*LINEAGE.DIAGNOSTIC_RELATIVE_PATH.parts)
            diagnostic.write_bytes(diagnostic.read_bytes() + b"\n")
            result = LINEAGE.load_and_validate_runner_diagnostic_lineage(
                workspace_root=root
            )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "runner_diagnostic_live_identity_mismatch", result["failures"]
        )

    def test_sidecar_path_and_identity_are_external_fixed_anchors(self):
        wrong = ROOT / "evidence" / "not-the-sidecar.json"
        result = LINEAGE.load_and_validate_runner_diagnostic_lineage(wrong)
        self.assertFalse(result["validated_pass"])
        self.assertEqual(
            result["failures"], ["runner_diagnostic_sidecar_path_mismatch"]
        )
        self.assertEqual(
            LINEAGE.SIDECAR_IDENTITY,
            {
                "path": LINEAGE.SIDECAR_RELATIVE_PATH.as_posix(),
                "size_bytes": 2119,
                "sha256": (
                    "e9136ea9166e85ac276000355c5e38f3280cfbe40de34fb902d302a6c353fed4"
                ),
            },
        )

    def test_strict_sidecar_payload_has_no_legacy_authority_selection(self):
        payload = LINEAGE.expected_sidecar_payload()
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        self.assertNotIn("ros1_canonical_source_binding_v7", encoded)
        self.assertNotIn("perception_v2_evidence_authority_index_20260814_v1", encoded)
        self.assertIn(LINEAGE.AUTHORITY_INDEX_ID, encoded)


if __name__ == "__main__":
    unittest.main()
