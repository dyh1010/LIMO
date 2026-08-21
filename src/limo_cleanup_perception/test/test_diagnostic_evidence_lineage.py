"""Tests for the isolated diagnostic-probe lineage authority."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest

from limo_cleanup_perception import diagnostic_evidence_lineage as LINEAGE


ROOT = Path(__file__).resolve().parents[3]
SIDECAR = ROOT / LINEAGE.SIDECAR_RELATIVE_PATH


def load_payload():
    return json.loads(SIDECAR.read_text(encoding="utf-8"))


class DiagnosticEvidenceLineageTest(unittest.TestCase):

    def assert_failed_with(self, payload, failure_prefix):
        result = LINEAGE.validate_diagnostic_evidence_lineage(payload)
        self.assertFalse(result["validated_pass"])
        self.assertFalse(result["delivery_ready"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertFalse(result["accepted_by_formal_evidence_consumer"])
        self.assertTrue(
            any(item.startswith(failure_prefix) for item in result["failures"]),
            result["failures"],
        )

    def test_canonical_sidecar_reopens_all_three_exact_artifacts(self):
        result = LINEAGE.load_and_validate_diagnostic_evidence_lineage()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertEqual(len(result["artifact_identities"]), 3)
        identities = {
            item["evidence_id"]: item for item in result["artifact_identities"]
        }
        self.assertEqual(
            identities["p2_field_gate_probe_20260814_v1"]["size_bytes"], 0
        )
        self.assertEqual(
            identities["p2_field_gate_probe_20260814_v1"]["sha256"],
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(
            result["current_evidence"]["evidence_id"],
            "p2_field_gate_probe_20260814_v3",
        )
        self.assertEqual(
            result["current_evidence"]["status"],
            "CURRENT_BLOCKED_DIAGNOSTIC_CHECKPOINT",
        )

    def test_lineage_never_authorizes_formal_or_field_delivery(self):
        result = LINEAGE.load_and_validate_diagnostic_evidence_lineage()
        self.assertTrue(result["validated_pass"], result["failures"])
        self.assertFalse(result["authorizes_motion"])
        self.assertFalse(result["authorizes_field_delivery"])
        self.assertFalse(result["accepted_by_formal_evidence_consumer"])
        self.assertFalse(result["delivery_ready"])
        self.assertEqual(result["formal_four_scene_frame_denominator"], 0)
        self.assertFalse(result["formal_tf_pass"])
        self.assertFalse(result["formal_3d_pass"])

    def test_zero_or_multiple_current_entries_fail_closed(self):
        zero = load_payload()
        for item in zero["entries"]:
            item["is_current"] = False
        self.assert_failed_with(zero, "diagnostic_lineage_current_count_invalid")

        multiple = load_payload()
        multiple["entries"][0]["is_current"] = True
        self.assert_failed_with(
            multiple, "diagnostic_lineage_current_count_invalid"
        )

    def test_path_size_hash_and_status_mismatch_fail_closed(self):
        mutations = (
            ("path", "C:\\not-the-probe.json"),
            ("size_bytes", 1),
            ("sha256", "0" * 64),
            ("status", "CURRENT_BLOCKED_DIAGNOSTIC_CHECKPOINT"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                payload = load_payload()
                payload["entries"][0][key] = value
                self.assert_failed_with(
                    payload,
                    "diagnostic_lineage_entry_mismatch:"
                    "p2_field_gate_probe_20260814_v1:"
                    + key,
                )

    def test_current_id_and_current_status_are_exact(self):
        wrong_id = load_payload()
        wrong_id["current_evidence_id"] = "p2_field_gate_probe_20260814_v2"
        self.assert_failed_with(
            wrong_id,
            "diagnostic_lineage_top_level_mismatch:current_evidence_id",
        )

        wrong_status = load_payload()
        wrong_status["entries"][2]["status"] = "ABORTED_EMPTY"
        self.assert_failed_with(
            wrong_status,
            "diagnostic_lineage_entry_mismatch:"
            "p2_field_gate_probe_20260814_v3:status",
        )

    def test_filename_and_mtime_cannot_become_authority(self):
        for key, value in (
            ("filename_mtime_selection_forbidden", False),
            ("uses_filename_or_mtime_authority", True),
            ("selection_authority", "NEWEST_MTIME"),
        ):
            with self.subTest(key=key):
                payload = load_payload()
                payload[key] = value
                self.assert_failed_with(
                    payload, "diagnostic_lineage_top_level_mismatch:" + key
                )

    def test_truthy_delivery_or_formal_flags_fail_closed(self):
        for scope in ("top", "entry"):
            for key in (
                "authorizes_field_delivery",
                "accepted_by_formal_evidence_consumer",
            ):
                with self.subTest(scope=scope, key=key):
                    payload = load_payload()
                    if scope == "top":
                        payload[key] = True
                        prefix = "diagnostic_lineage_top_level_mismatch:" + key
                    else:
                        payload["entries"][2][key] = True
                        prefix = (
                            "diagnostic_lineage_entry_mismatch:"
                            "p2_field_gate_probe_20260814_v3:" + key
                        )
                    self.assert_failed_with(payload, prefix)

    def test_missing_extra_and_duplicate_entry_identity_fail_closed(self):
        missing = load_payload()
        missing.pop("lineage_scope")
        self.assert_failed_with(
            missing, "diagnostic_lineage_top_level_keys_invalid"
        )

        extra = load_payload()
        extra["mtime"] = 0
        self.assert_failed_with(extra, "diagnostic_lineage_top_level_keys_invalid")

        duplicate = load_payload()
        duplicate["entries"][1]["evidence_id"] = duplicate["entries"][0][
            "evidence_id"
        ]
        self.assert_failed_with(
            duplicate, "diagnostic_lineage_duplicate_evidence_id"
        )

    def test_wrong_sidecar_path_and_source_surface_fail_closed(self):
        result = LINEAGE.load_and_validate_diagnostic_evidence_lineage(
            SIDECAR.with_name("not_the_authority.json")
        )
        self.assertFalse(result["validated_pass"])
        self.assertIn(
            "diagnostic_lineage_sidecar_path_mismatch", result["failures"]
        )

        source_path = Path(LINEAGE.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(
            imported
            & {
                "rospy",
                "rclpy",
                "geometry_msgs",
                "actionlib",
                "move_base_msgs",
            }
        )
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn("cmd_vel", source)
        self.assertNotIn("Publisher(", source)


if __name__ == "__main__":
    unittest.main()
