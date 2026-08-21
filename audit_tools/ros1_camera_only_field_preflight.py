"""Host-owned static preflight for a ROS1/Noetic camera-only field window.

The preflight is deliberately inert.  It does not source a ROS setup file,
run a command, import a ROS module, start a graph, open a camera, run inference,
or publish anything.  A successful result means only that the frozen lineage,
the archived vendor reference, the exact live vendor launch, the formal launch,
and a local Noetic toolchain surface were found and passed static checks.  It
can never authorize formal evidence or delivery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "ros1_camera_only_field_preflight/v1"
PREFLIGHT_ID = "ROS1_NOETIC_CAMERA_ONLY_STATIC_PREFLIGHT_V1"
MARKER = "ROS1_CAMERA_ONLY_FIELD_PREFLIGHT "
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

PREDECESSOR_AUTHORITY_V4: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_formal_admission_evidence_authority_index_20260815_v4.json"
    ),
    "size_bytes": 5015,
    "sha256": "6de0170caad03b0d89c64ce611cb406e18763f07218ed97c98167a86224d5ded",
}
FROZEN_CANONICAL_V5: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "ros1_noetic_canonical_source_admission_20260815_v5.json"
    ),
    "size_bytes": 9889,
    "sha256": "1c4a9c2901cae292803cec4a700550c2054a26b94e1ae89aacbedb3865e7801a",
}
FROZEN_REPORT_V4: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_offline_20260813/"
        "frozen_offline_regression_20260815_runner_platform_composite_v4.json"
    ),
    "size_bytes": 1288709,
    "sha256": "dfa7e3f8c53f6157fec5083b26b8fc87b3115dcfb9eb6fbbde2fbcf52775c5be",
}
DABAI_LAUNCH: Mapping[str, Any] = {
    "path": (
        "evidence/perception_v2_field_20260814/"
        "ros1_launch_source/dabai_u3.launch"
    ),
    "size_bytes": 6446,
    "sha256": "75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e",
}
PRODUCTION_VENDOR_LAUNCH_PATH = (
    "/opt/limo/ros1_camera_runtime/share/astra_camera/launch/dabai_u3.launch"
)
FORMAL_CAPTURE_LAUNCH: Mapping[str, Any] = {
    "path": (
        "ros1_overlay_src/limo_cleanup_ros1_perception/"
        "launch/perception_v2_formal_capture.launch"
    ),
    "size_bytes": 1633,
    "sha256": "c835d006d403c89dd61ce8bf76488a2093297bf3c04902799b82b688927c9d42",
}

EXPECTED_CURRENT_EVIDENCE_ID = (
    "ros1_runner_platform_composite_offline_regression_20260815_v4"
)
EXPECTED_INDEX_INSTANCE_ID = (
    "ros1-formal-admission-evidence-authority-index-20260815-v4"
)
EXPECTED_CANONICAL_ID = "ros1_noetic_canonical_source_admission_20260815_v5"

NOETIC_SETUP_PATH = "/opt/ros/noetic/setup.bash"
CATKIN_MAKE_CANDIDATES = (
    "/opt/ros/noetic/bin/catkin_make",
    "/usr/bin/catkin_make",
    "/usr/local/bin/catkin_make",
)
CMAKE_CANDIDATES = ("/usr/bin/cmake", "/usr/local/bin/cmake")

CONTROL_TOKENS = (
    "cmd_vel",
    "move_base",
    "controller",
    "arm_controller",
    "gripper",
    "geometry_msgs/twist",
    "twist",
    "move_base_msgs",
    "actionlib",
    "goal",
)

# Exact semantic structure of the frozen 6,446-byte DaBai launch.  This is
# intentionally a literal policy rather than a set of merely required fields:
# a future vendor launch generation must receive a new audited policy instead
# of silently growing the executable ROS surface.
DABAI_ARG_DEFAULTS: Tuple[Tuple[str, str], ...] = (
    ("camera_name", "camera"),
    ("depth_align", "false"),
    ("serial_number", ""),
    ("device_num", "1"),
    ("vendor_id", "0x2bc5"),
    ("product_id", ""),
    ("enable_point_cloud", "true"),
    ("enable_point_cloud_xyzrgb", "false"),
    ("connection_delay", "100"),
    ("color_width", "640"),
    ("color_height", "480"),
    ("color_fps", "30"),
    ("enable_color", "true"),
    ("flip_color", "false"),
    ("color_format", "RGB"),
    ("depth_width", "640"),
    ("depth_height", "400"),
    ("depth_fps", "30"),
    ("enable_depth", "true"),
    ("flip_depth", "false"),
    ("depth_format", "Y11"),
    ("ir_width", "640"),
    ("ir_height", "480"),
    ("ir_fps", "30"),
    ("enable_ir", "true"),
    ("ir_format", "Y10"),
    ("flip_ir", "false"),
    ("publish_tf", "true"),
    ("tf_publish_rate", "10.0"),
    ("ir_info_uri", ""),
    ("color_info_uri", ""),
    ("color_roi_x", "-1"),
    ("color_roi_y", "-1"),
    ("color_roi_width", "-1"),
    ("color_roi_height", "-1"),
    ("depth_roi_x", "-1"),
    ("depth_roi_y", "-1"),
    ("depth_roi_width", "-1"),
    ("depth_roi_height", "-1"),
    ("depth_scale", "1"),
    ("color_depth_synchronization", "false"),
    ("use_uvc_camera", "true"),
    ("uvc_vendor_id", "0x2bc5"),
    ("uvc_product_id", "0x050e"),
    ("uvc_retry_count", "100"),
    ("uvc_camera_format", "mjpeg"),
    ("uvc_flip", "false"),
    ("oni_log_level", "verbose"),
    ("oni_log_to_console", "false"),
    ("oni_log_to_file", "false"),
    ("enable_d2c_viewer", "false"),
    ("enable_publish_extrinsic", "false"),
)

DABAI_PARAM_ORDER: Tuple[str, ...] = (
    "camera_name", "depth_align", "serial_number", "device_num",
    "vendor_id", "product_id", "enable_point_cloud",
    "enable_point_cloud_xyzrgb", "connection_delay", "color_width",
    "color_height", "color_fps", "enable_color", "color_format",
    "flip_color", "depth_width", "depth_height", "depth_fps",
    "flip_depth", "enable_depth", "depth_format", "ir_width",
    "ir_height", "ir_fps", "enable_ir", "flip_ir", "ir_format",
    "publish_tf", "tf_publish_rate", "ir_info_uri", "color_info_uri",
    "color_roi_x", "color_roi_y", "color_roi_width", "color_roi_height",
    "depth_roi_x", "depth_roi_y", "depth_roi_width", "depth_roi_height",
    "depth_scale", "color_depth_synchronization", "use_uvc_camera",
    "uvc_vendor_id", "uvc_product_id", "uvc_retry_count",
    "uvc_camera_format", "uvc_flip", "oni_log_level",
    "oni_log_to_console", "oni_log_to_file", "enable_d2c_viewer",
    "enable_publish_extrinsic",
)

DABAI_GROUP_ATTRIBUTES: Mapping[str, str] = {
    "ns": "$(arg camera_name)",
}
DABAI_NODE_ATTRIBUTES: Mapping[str, str] = {
    "name": "camera",
    "pkg": "astra_camera",
    "type": "astra_camera_node",
    "output": "screen",
}
DABAI_REMAP_ATTRIBUTES: Mapping[str, str] = {
    "from": "/$(arg camera_name)/depth/color/points",
    "to": "/$(arg camera_name)/depth_registered/points",
}


class StrictJsonError(ValueError):
    """Raised for duplicate JSON keys or non-finite constants."""


def _reject_constant(value: str) -> None:
    raise StrictJsonError("non_finite_json_constant:" + value)


def _strict_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _artifact_path(workspace_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError("artifact_relative_path_invalid")
    return workspace_root.joinpath(*pure.parts)


def _snapshot(value: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _is_linklike(value: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(value, "st_file_attributes", 0))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _node_identity(value: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "link_count": int(value.st_nlink),
        "size_bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "file_attributes": int(getattr(value, "st_file_attributes", 0)),
    }


def _parent_chain_is_non_link(path: Path, root: Path) -> bool:
    current = path.parent
    resolved_root = root.resolve(strict=True)
    while True:
        try:
            info = current.lstat()
        except OSError:
            return False
        if _is_linklike(info):
            return False
        if current.resolve(strict=True) == resolved_root:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _read_exact_artifact(
        workspace_root: Path,
        expected: Mapping[str, Any],
        failure_prefix: str) -> Tuple[Dict[str, Any], Optional[bytes], List[str]]:
    failures: List[str] = []
    report: Dict[str, Any] = {
        "path": expected.get("path"),
        "expected_size_bytes": expected.get("size_bytes"),
        "expected_sha256": expected.get("sha256"),
        "regular_non_link": False,
        "identity_matches": False,
    }
    try:
        root = workspace_root.resolve(strict=True)
        path = _artifact_path(root, str(expected["path"]))
        if not _within(path.resolve(strict=False), root):
            failures.append(failure_prefix + "_path_escape")
            return report, None, failures
        if not _parent_chain_is_non_link(path, root):
            failures.append(failure_prefix + "_parent_linklike")
            return report, None, failures
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            failures.append(failure_prefix + "_artifact_linklike_or_nonregular")
            return report, None, failures
        with path.open("rb") as stream:
            raw = stream.read()
        after = path.lstat()
        if _snapshot(before) != _snapshot(after):
            failures.append(failure_prefix + "_artifact_changed_during_read")
            return report, None, failures
        observed_sha = _sha256(raw)
        report.update({
            "regular_non_link": True,
            "size_bytes": len(raw),
            "sha256": observed_sha,
        })
        if len(raw) != expected["size_bytes"]:
            failures.append(failure_prefix + "_size_bytes_mismatch")
        if observed_sha != expected["sha256"]:
            failures.append(failure_prefix + "_sha256_mismatch")
        report["identity_matches"] = not failures
        return report, raw, failures
    except (KeyError, OSError, TypeError, ValueError):
        failures.append(failure_prefix + "_artifact_unavailable")
        return report, None, failures


def _absolute_parent_chain_identity(
        path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    chain: List[Dict[str, Any]] = []
    current = path.parent
    try:
        while True:
            info = current.lstat()
            item = {"path": str(current), **_node_identity(info)}
            chain.append(item)
            if _is_linklike(info):
                return chain, ["parent_chain_linklike"]
            if not stat.S_ISDIR(info.st_mode):
                return chain, ["parent_chain_non_directory"]
            if current.parent == current:
                return chain, []
            current = current.parent
    except OSError:
        return chain, ["parent_chain_unavailable"]


def _read_absolute_vendor_launch(
        actual_path: Optional[Path],
        expected_path: Path,
        failure_prefix: str) -> Tuple[Dict[str, Any], Optional[bytes], List[str]]:
    report: Dict[str, Any] = {
        "requested_path": None if actual_path is None else str(actual_path),
        "required_exact_path": str(expected_path),
        "expected_basename": "dabai_u3.launch",
        "expected_size_bytes": DABAI_LAUNCH["size_bytes"],
        "expected_sha256": DABAI_LAUNCH["sha256"],
        "absolute_path": False,
        "parent_chain_non_link": False,
        "unique_regular_non_link": False,
        "identity_matches_frozen_reference": False,
    }
    failures: List[str] = []
    if actual_path is None:
        return report, None, [failure_prefix + "_required"]
    try:
        path = Path(actual_path)
        if not path.is_absolute():
            return report, None, [failure_prefix + "_path_not_absolute"]
        if (".." in path.parts
                or path.name != "dabai_u3.launch"):
            return report, None, [failure_prefix + "_path_policy_mismatch"]
        path = path.absolute()
        if path != expected_path.absolute():
            return report, None, [failure_prefix + "_exact_path_mismatch"]
        report["path"] = str(path)
        report["absolute_path"] = True

        parent_before, parent_failures = _absolute_parent_chain_identity(path)
        report["parent_chain_identity"] = parent_before
        if parent_failures:
            return report, None, [
                failure_prefix + "_" + item for item in parent_failures]
        report["parent_chain_non_link"] = True

        before = path.lstat()
        if _is_linklike(before) or not stat.S_ISREG(before.st_mode):
            return report, None, [
                failure_prefix + "_artifact_linklike_or_nonregular"]
        if int(before.st_nlink) != 1:
            return report, None, [failure_prefix + "_artifact_not_unique"]
        resolved_before = path.resolve(strict=True)
        if resolved_before != path:
            return report, None, [failure_prefix + "_resolved_target_mismatch"]
        raw = path.read_bytes()
        after = path.lstat()
        resolved_after = path.resolve(strict=True)
        parent_after, parent_after_failures = _absolute_parent_chain_identity(path)
        if parent_after_failures:
            return report, None, [
                failure_prefix + "_" + item for item in parent_after_failures]
        if (resolved_after != resolved_before
                or _snapshot(before) != _snapshot(after)
                or _node_identity(before) != _node_identity(after)
                or parent_after != parent_before):
            return report, None, [failure_prefix + "_changed_during_read"]

        observed_sha = _sha256(raw)
        report.update({
            "resolved_path": str(resolved_after),
            "filesystem_identity": _node_identity(after),
            "size_bytes": len(raw),
            "sha256": observed_sha,
            "unique_regular_non_link": True,
        })
        if len(raw) != DABAI_LAUNCH["size_bytes"]:
            failures.append(failure_prefix + "_size_bytes_mismatch")
        if observed_sha != DABAI_LAUNCH["sha256"]:
            failures.append(failure_prefix + "_sha256_mismatch")
        report["identity_matches_frozen_reference"] = not failures
        return report, raw, failures
    except (OSError, RuntimeError, TypeError, ValueError):
        return report, None, [failure_prefix + "_unavailable"]


def _validate_predecessor_payload(raw: Optional[bytes]) -> List[str]:
    if raw is None:
        return []
    failure = "predecessor_authority_v4_semantic_mismatch"
    try:
        value = _strict_json(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, StrictJsonError):
        return ["predecessor_authority_v4_strict_json_invalid"]
    if not isinstance(value, dict):
        return [failure]
    checks = (
        value.get("schema_version") == "ros1_formal_admission_evidence_authority/v3",
        value.get("index_instance_id") == EXPECTED_INDEX_INSTANCE_ID,
        value.get("current_evidence_id") == EXPECTED_CURRENT_EVIDENCE_ID,
        value.get("accepted_as_offline_release_selection_authority") is True,
        value.get("accepted_by_formal_field_evidence_consumer") is False,
        value.get("authorizes_field_delivery") is False,
        value.get("authorizes_motion") is False,
        value.get("read_only") is True,
        value.get("immutable") is True,
        value.get("filename_mtime_selection_forbidden") is True,
        value.get("uses_filename_or_mtime_authority") is False,
    )
    entries = value.get("entries")
    currents = (
        [item for item in entries
         if isinstance(item, dict) and item.get("is_current") is True]
        if isinstance(entries, list) else []
    )
    children = value.get("child_artifacts")
    canonical = (
        [item for item in children
         if isinstance(item, dict)
         and item.get("artifact_id") == EXPECTED_CANONICAL_ID]
        if isinstance(children, list) else []
    )
    gate = value.get("gate_state")
    semantic_ok = (
        all(checks)
        and len(currents) == 1
        and currents[0].get("evidence_id") == EXPECTED_CURRENT_EVIDENCE_ID
        and currents[0].get("delivery_ready") is False
        and currents[0].get("authorizes_field_delivery") is False
        and currents[0].get("regression_passed") is False
        and len(canonical) == 1
        and canonical[0].get("path") == FROZEN_CANONICAL_V5["path"]
        and canonical[0].get("size_bytes") == FROZEN_CANONICAL_V5["size_bytes"]
        and canonical[0].get("sha256") == FROZEN_CANONICAL_V5["sha256"]
        and isinstance(gate, dict)
        and gate.get("delivery_ready") is False
        and gate.get("authorizes_field_delivery") is False
        and gate.get("formal_four_scene_frame_denominator") == 0
        and gate.get("formal_tf_pass") is False
        and gate.get("formal_3d_pass") is False
        and gate.get("formal_latency_pass") is False
        and gate.get("ros1_noetic_build_install_verified") is False
        and gate.get("ros1_noetic_field_install_pass") is False
    )
    return [] if semantic_ok else [failure]


def _xml_root(raw: bytes) -> ET.Element:
    text = raw.decode("utf-8", errors="strict")
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("xml_entity_or_doctype_forbidden")
    return ET.fromstring(text)


def _control_token_failures(raw: bytes, prefix: str) -> List[str]:
    text = raw.decode("utf-8", errors="strict").lower()
    failures = []
    for token in CONTROL_TOKENS:
        if token in text:
            failures.append(prefix + "_control_token:" + token)
    return failures


def _validate_dabai_launch_bytes(raw: bytes) -> List[str]:
    failures: List[str] = []
    try:
        root = _xml_root(raw)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        return ["dabai_launch_xml_invalid"]
    failures.extend(_control_token_failures(raw, "dabai_launch"))
    lowered = raw.decode("utf-8", errors="strict").lower()
    for substitution in ("$(env ", "$(optenv ", "$(eval "):
        if substitution in lowered:
            failures.append("dabai_launch_forbidden_substitution")
    if root.tag != "launch" or root.attrib:
        failures.append("dabai_launch_root_invalid")
    # Text and nested children are not executable surface in the baseline.
    # Reject them explicitly so ElementTree's permissive parsing cannot hide
    # a future command/textfile/binfile-style expansion.
    if root.text is not None and root.text.strip():
        failures.append("dabai_launch_non_whitespace_text")

    children = list(root)
    expected_root_tags = ["arg"] * len(DABAI_ARG_DEFAULTS) + ["group"]
    if [item.tag for item in children] != expected_root_tags:
        failures.append("dabai_launch_exact_root_children_mismatch")

    args = children[:len(DABAI_ARG_DEFAULTS)]
    if len(args) != len(DABAI_ARG_DEFAULTS):
        failures.append("dabai_launch_arg_count_mismatch")
    for index, expected in enumerate(DABAI_ARG_DEFAULTS):
        if index >= len(args):
            break
        item = args[index]
        name, default = expected
        if item.tag != "arg" or item.attrib != {
                "name": name, "default": default}:
            failures.append("dabai_launch_arg_policy_mismatch:" + name)
        if list(item) or (item.text is not None and item.text.strip()):
            failures.append("dabai_launch_arg_nested_content:" + name)

    groups = [item for item in children if item.tag == "group"]
    if len(groups) != 1 or groups[0].attrib != DABAI_GROUP_ATTRIBUTES:
        failures.append("dabai_launch_group_policy_mismatch")
        return sorted(set(failures))
    group = groups[0]
    if group.text is not None and group.text.strip():
        failures.append("dabai_launch_group_non_whitespace_text")
    group_children = list(group)
    if len(group_children) != 1 or group_children[0].tag != "node":
        failures.append("dabai_launch_group_exact_children_mismatch")
        return sorted(set(failures))

    node = group_children[0]
    if node.attrib != DABAI_NODE_ATTRIBUTES:
        failures.append("dabai_launch_camera_node_policy_mismatch")
    if node.text is not None and node.text.strip():
        failures.append("dabai_launch_node_non_whitespace_text")
    node_children = list(node)
    expected_node_tags = ["param"] * len(DABAI_PARAM_ORDER) + ["remap"]
    if [item.tag for item in node_children] != expected_node_tags:
        failures.append("dabai_launch_exact_node_children_mismatch")

    params = node_children[:len(DABAI_PARAM_ORDER)]
    if len(params) != len(DABAI_PARAM_ORDER):
        failures.append("dabai_launch_param_count_mismatch")
    for index, name in enumerate(DABAI_PARAM_ORDER):
        if index >= len(params):
            break
        item = params[index]
        expected_attributes = {
            "name": name,
            "value": "$(arg {})".format(name),
        }
        if name == "serial_number":
            expected_attributes["type"] = "string"
        if item.tag != "param" or item.attrib != expected_attributes:
            failures.append("dabai_launch_param_policy_mismatch:" + name)
        if list(item) or (item.text is not None and item.text.strip()):
            failures.append("dabai_launch_param_nested_content:" + name)

    remaps = node_children[len(DABAI_PARAM_ORDER):]
    if (len(remaps) != 1
            or remaps[0].tag != "remap"
            or remaps[0].attrib != DABAI_REMAP_ATTRIBUTES
            or list(remaps[0])
            or (remaps[0].text is not None and remaps[0].text.strip())):
        failures.append("dabai_launch_remap_policy_mismatch")

    # Unknown descendants can only arrive through a malformed leaf because
    # every allowed container and child sequence was enumerated above.
    allowed_tags = {"launch", "arg", "group", "node", "param", "remap"}
    if any(item.tag not in allowed_tags for item in root.iter()):
        failures.append("dabai_launch_unknown_element")
    return sorted(set(failures))


FORMAL_ARGS: Mapping[str, Optional[str]] = {
    "rgb_topic": "/camera/color/image_raw",
    "depth_topic": "/camera/depth/image_raw",
    "rgb_camera_info_topic": "/camera/color/camera_info",
    "depth_camera_info_topic": "/camera/depth/camera_info",
    "model_manifest": (
        "$(find limo_cleanup_ros1_perception)/config/model_bindings.json"
    ),
    "task_id": None,
    "capture_id": None,
}
FORMAL_PARAMS: Mapping[str, str] = {
    "rgb_topic": "$(arg rgb_topic)",
    "depth_topic": "$(arg depth_topic)",
    "rgb_camera_info_topic": "$(arg rgb_camera_info_topic)",
    "depth_camera_info_topic": "$(arg depth_camera_info_topic)",
    "model_manifest": "$(arg model_manifest)",
    "formal_capture_mode": "true",
    "task_id": "$(arg task_id)",
    "capture_id": "$(arg capture_id)",
    "confidence": "0.35",
    "iou": "0.45",
    "image_size": "640",
    "max_sync_delta_sec": "0.15",
    "depth_scale": "0.001",
    "opening_height_ratio": "0.62",
    "in_bin_overlap": "0.30",
}


def _validate_formal_launch_bytes(raw: bytes) -> List[str]:
    failures: List[str] = []
    try:
        root = _xml_root(raw)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        return ["formal_capture_launch_xml_invalid"]
    failures.extend(_control_token_failures(raw, "formal_capture_launch"))
    lowered = raw.decode("utf-8", errors="strict").lower()
    for substitution in ("$(env ", "$(optenv ", "$(eval "):
        if substitution in lowered:
            failures.append("formal_capture_launch_forbidden_substitution")
    if root.tag != "launch" or root.attrib:
        failures.append("formal_capture_launch_root_invalid")
    children = list(root)
    if len(children) != len(FORMAL_ARGS) + 1:
        failures.append("formal_capture_launch_child_count_mismatch")
    if any(item.tag not in {"arg", "node"} for item in children):
        failures.append("formal_capture_launch_element_not_allowlisted")
    args = [item for item in children if item.tag == "arg"]
    if len(args) != len(FORMAL_ARGS):
        failures.append("formal_capture_launch_arg_count_mismatch")
    observed_args: Dict[str, Optional[str]] = {}
    for item in args:
        name = item.attrib.get("name")
        if name in observed_args or name not in FORMAL_ARGS:
            failures.append("formal_capture_launch_arg_set_mismatch")
            continue
        expected_default = FORMAL_ARGS[name]
        expected_attributes = {"name": name}
        if expected_default is not None:
            expected_attributes["default"] = expected_default
        if item.attrib != expected_attributes:
            failures.append("formal_capture_launch_arg_policy_mismatch:" + name)
        observed_args[name] = item.attrib.get("default")
    if set(observed_args) != set(FORMAL_ARGS):
        failures.append("formal_capture_launch_arg_set_mismatch")
    nodes = [item for item in children if item.tag == "node"]
    if len(nodes) != 1:
        failures.append("formal_capture_launch_node_count_mismatch")
        return sorted(set(failures))
    node = nodes[0]
    if node.attrib != {
            "pkg": "limo_cleanup_ros1_perception",
            "type": "dual_model_detector.py",
            "name": "cleanup_dual_model_detector",
            "output": "screen",
            "required": "true"}:
        failures.append("formal_capture_launch_node_policy_mismatch")
    node_children = list(node)
    if any(item.tag != "param" for item in node_children):
        failures.append("formal_capture_launch_node_child_not_allowlisted")
    if len(node_children) != len(FORMAL_PARAMS):
        failures.append("formal_capture_launch_param_count_mismatch")
    observed_params: Dict[str, str] = {}
    for item in node_children:
        if item.tag != "param":
            continue
        name = item.attrib.get("name")
        if name in observed_params or name not in FORMAL_PARAMS:
            failures.append("formal_capture_launch_param_set_mismatch")
            continue
        if item.attrib != {"name": name, "value": FORMAL_PARAMS[name]}:
            failures.append("formal_capture_launch_param_policy_mismatch:" + name)
        observed_params[name] = item.attrib.get("value", "")
    if set(observed_params) != set(FORMAL_PARAMS):
        failures.append("formal_capture_launch_param_set_mismatch")
    return sorted(set(failures))


def _rooted(environment_root: Path, absolute_path: str) -> Path:
    pure = PurePosixPath(absolute_path)
    if not pure.is_absolute() or ".." in pure.parts:
        raise ValueError("environment_candidate_path_invalid")
    return environment_root.joinpath(*pure.parts[1:])


def _display_environment_path(path: Path, environment_root: Path) -> str:
    try:
        relative = path.relative_to(environment_root)
    except ValueError:
        return str(path)
    return "/" + PurePosixPath(*relative.parts).as_posix()


def _regular_file_identity(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    report: Dict[str, Any] = {"path": str(path), "validated": False}
    failures: List[str] = []
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            return report, ["regular_non_link_file_required"]
        raw = path.read_bytes()
        after = path.lstat()
        if _snapshot(before) != _snapshot(after):
            return report, ["file_changed_during_read"]
        report.update({
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
            "regular_non_link": True,
            "validated": True,
        })
    except OSError:
        failures.append("file_unavailable")
    return report, failures


def _executable_identity(
        path: Path, environment_root: Path) -> Tuple[Dict[str, Any], List[str]]:
    report: Dict[str, Any] = {
        "entry_path": _display_environment_path(path, environment_root),
        "validated": False,
    }
    try:
        root = environment_root.resolve(strict=True)
        entry = path.absolute()
        if not _within(entry, root):
            return report, ["executable_path_outside_environment_root"]
        before_entry = entry.lstat()
        target = entry.resolve(strict=True)
        if not _within(target, root):
            return report, ["executable_target_outside_environment_root"]
        target_before = target.lstat()
        if stat.S_ISLNK(target_before.st_mode) or not stat.S_ISREG(
                target_before.st_mode):
            return report, ["executable_target_not_regular"]
        if os.name != "nt" and not os.access(str(target), os.X_OK):
            return report, ["executable_target_not_executable"]
        raw = target.read_bytes()
        target_after = target.lstat()
        after_entry = entry.lstat()
        if (_snapshot(before_entry) != _snapshot(after_entry)
                or _snapshot(target_before) != _snapshot(target_after)):
            return report, ["executable_changed_during_read"]
        report.update({
            "entry_is_symlink": stat.S_ISLNK(before_entry.st_mode),
            "resolved_target_path": _display_environment_path(target, root),
            "target_size_bytes": len(raw),
            "target_sha256": _sha256(raw),
            "target_regular_non_link": True,
            "validated": True,
        })
        if report["entry_is_symlink"]:
            report["entry_link_text"] = os.readlink(str(entry))
        return report, []
    except (OSError, RuntimeError, ValueError):
        return report, ["executable_unavailable_or_link_chain_invalid"]


def _first_executable(
        environment_root: Path,
        candidates: Sequence[str]) -> Tuple[Optional[Path], List[str]]:
    for item in candidates:
        try:
            path = _rooted(environment_root, item)
            path.lstat()
            return path, []
        except OSError:
            continue
    return None, list(candidates)


def _toolchain_report(
        environment_root: Path,
        python_executable: Path,
        python_version: Tuple[int, int, int]) -> Tuple[Dict[str, Any], List[str]]:
    failures: List[str] = []
    root = environment_root.resolve(strict=True)
    setup_path = _rooted(root, NOETIC_SETUP_PATH)
    setup, setup_failures = _regular_file_identity(setup_path)
    setup["path"] = NOETIC_SETUP_PATH
    if setup_failures:
        failures.append("ROS1_NOETIC_SETUP_BASH_NOT_AVAILABLE")

    catkin_path, catkin_candidates = _first_executable(root, CATKIN_MAKE_CANDIDATES)
    if catkin_path is None:
        catkin = {"validated": False, "candidates": catkin_candidates}
        failures.append("ROS1_CATKIN_MAKE_NOT_AVAILABLE")
    else:
        catkin, catkin_failures = _executable_identity(catkin_path, root)
        if catkin_failures:
            catkin["identity_failures"] = catkin_failures
            failures.append("ROS1_CATKIN_MAKE_IDENTITY_INVALID")

    cmake_path, cmake_candidates = _first_executable(root, CMAKE_CANDIDATES)
    if cmake_path is None:
        cmake = {"validated": False, "candidates": cmake_candidates}
        failures.append("ROS1_CMAKE_NOT_AVAILABLE")
    else:
        cmake, cmake_failures = _executable_identity(cmake_path, root)
        if cmake_failures:
            cmake["identity_failures"] = cmake_failures
            failures.append("ROS1_CMAKE_IDENTITY_INVALID")

    python, python_failures = _executable_identity(python_executable, root)
    python["version"] = list(python_version)
    python["major_is_three"] = python_version[0] == 3
    if python_failures or not python["major_is_three"]:
        if python_failures:
            python["identity_failures"] = python_failures
        failures.append("ROS1_PYTHON_EXECUTABLE_IDENTITY_INVALID")

    if failures:
        failures.append("ROS1_NOETIC_TOOLCHAIN_NOT_AVAILABLE")
    return {
        "environment_root": str(root),
        "inspection_only": True,
        "sources_ros_setup": False,
        "runs_external_commands": False,
        "noetic_setup_bash": setup,
        "catkin_make": catkin,
        "cmake": cmake,
        "python": python,
        "validated_pass": not failures,
    }, sorted(set(failures))


def evaluate_preflight(
        workspace_root: Path = WORKSPACE_ROOT,
        environment_root: Path = Path("/"),
        actual_vendor_launch: Optional[Path] = None,
        python_executable: Optional[Path] = None,
        python_version: Optional[Tuple[int, int, int]] = None) -> Dict[str, Any]:
    """Recompute the inert static preflight from files on disk."""
    failures: List[str] = []
    root = workspace_root.resolve(strict=True)
    environment = environment_root.resolve(strict=True)

    predecessor, predecessor_raw, found = _read_exact_artifact(
        root, PREDECESSOR_AUTHORITY_V4, "predecessor_authority_v4")
    failures.extend(found)
    semantic_failures = _validate_predecessor_payload(predecessor_raw)
    failures.extend(semantic_failures)
    predecessor["semantic_valid"] = not semantic_failures
    predecessor["reference_role"] = "FROZEN_PREDECESSOR_ONLY"
    predecessor["selected_as_new_field_authority"] = False

    canonical, _, found = _read_exact_artifact(
        root, FROZEN_CANONICAL_V5, "frozen_canonical_v5_reference")
    failures.extend(found)
    canonical["reference_role"] = "FROZEN_PREDECESSOR_CHILD_ONLY"
    canonical["reinterpreted_for_live_source"] = False

    report, _, found = _read_exact_artifact(
        root, FROZEN_REPORT_V4, "frozen_report_v4_reference")
    failures.extend(found)
    report["reference_role"] = "FROZEN_PREDECESSOR_REPORT_ONLY"
    report["reinterpreted_as_field_evidence"] = False

    dabai, dabai_raw, found = _read_exact_artifact(
        root, DABAI_LAUNCH, "dabai_launch_archive_reference")
    failures.extend(found)
    dabai_semantics = (
        _validate_dabai_launch_bytes(dabai_raw) if dabai_raw is not None else [])
    failures.extend(
        "dabai_launch_archive_reference_semantic:" + item
        for item in dabai_semantics)
    dabai["semantic_failures"] = dabai_semantics
    dabai["reference_role"] = "FROZEN_VENDOR_LAUNCH_REFERENCE_ONLY"
    dabai["selected_as_execution_target"] = False
    dabai["static_camera_only_semantics_pass"] = (
        dabai.get("identity_matches") is True and not dabai_semantics)

    expected_live_path = Path(PRODUCTION_VENDOR_LAUNCH_PATH)
    live, live_raw, found = _read_absolute_vendor_launch(
        actual_vendor_launch, expected_live_path, "actual_vendor_launch")
    failures.extend(found)
    archive_path = root.joinpath(*Path(DABAI_LAUNCH["path"]).parts)
    try:
        live_reuses_archive = (
            actual_vendor_launch is not None
            and Path(actual_vendor_launch).is_absolute()
            and Path(actual_vendor_launch).resolve(strict=True)
            == archive_path.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        live_reuses_archive = False
    if live_reuses_archive:
        failures.append("actual_vendor_launch_reuses_archive_reference")
    live_semantics = (
        _validate_dabai_launch_bytes(live_raw) if live_raw is not None else [])
    failures.extend(
        "actual_vendor_launch_semantic:" + item
        for item in live_semantics)
    post_live, post_live_raw, post_failures = _read_absolute_vendor_launch(
        actual_vendor_launch, expected_live_path,
        "actual_vendor_launch_postcheck")
    failures.extend(post_failures)
    stable_across_validation = (
        live_raw is not None
        and post_live_raw is not None
        and live_raw == post_live_raw
        and live.get("resolved_path") == post_live.get("resolved_path")
        and live.get("filesystem_identity") == post_live.get("filesystem_identity")
        and live.get("size_bytes") == post_live.get("size_bytes")
        and live.get("sha256") == post_live.get("sha256")
        and live.get("parent_chain_identity")
        == post_live.get("parent_chain_identity"))
    if live_raw is not None and not stable_across_validation:
        failures.append("actual_vendor_launch_identity_changed_after_validation")
    archive_live_identity_match = (
        dabai_raw is not None
        and live_raw is not None
        and dabai_raw == live_raw
        and dabai.get("size_bytes") == live.get("size_bytes")
        and dabai.get("sha256") == live.get("sha256"))
    if live_raw is not None and not archive_live_identity_match:
        failures.append("actual_vendor_launch_archive_identity_mismatch")
    live.update({
        "execution_target_role": "EXPLICIT_LIVE_VENDOR_LAUNCH",
        "archive_reference_path": DABAI_LAUNCH["path"],
        "production_required_path": PRODUCTION_VENDOR_LAUNCH_PATH,
        "reuses_archive_reference": live_reuses_archive,
        "semantic_failures": live_semantics,
        "post_validation_identity": post_live,
        "stable_across_semantic_validation": stable_across_validation,
        "archive_live_identity_match": archive_live_identity_match,
        "static_camera_only_semantics_pass": (
            live.get("identity_matches_frozen_reference") is True
            and post_live.get("identity_matches_frozen_reference") is True
            and stable_across_validation
            and archive_live_identity_match
            and not live_reuses_archive
            and not live_semantics),
    })

    formal, formal_raw, found = _read_exact_artifact(
        root, FORMAL_CAPTURE_LAUNCH, "formal_capture_launch")
    failures.extend(found)
    formal_semantics = (
        _validate_formal_launch_bytes(formal_raw)
        if formal_raw is not None else [])
    failures.extend(formal_semantics)
    formal["semantic_failures"] = formal_semantics
    formal["task_id_must_be_explicit"] = True
    formal["capture_id_must_be_explicit"] = True
    formal["static_read_only_semantics_pass"] = (
        formal.get("identity_matches") is True and not formal_semantics)

    selected_python = (
        Path(sys.executable) if python_executable is None else python_executable)
    selected_version = (
        (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        if python_version is None else python_version)
    toolchain, toolchain_failures = _toolchain_report(
        environment, selected_python, selected_version)
    failures.extend(toolchain_failures)

    failures = sorted(set(failures))
    lineage_reference_pass = (
        predecessor.get("identity_matches") is True
        and predecessor.get("semantic_valid") is True
        and canonical.get("identity_matches") is True
        and report.get("identity_matches") is True)
    static_launch_safety_pass = (
        dabai.get("static_camera_only_semantics_pass") is True
        and live.get("static_camera_only_semantics_pass") is True
        and formal.get("static_read_only_semantics_pass") is True)
    preflight_pass = (
        lineage_reference_pass
        and static_launch_safety_pass
        and toolchain.get("validated_pass") is True
        and not failures)
    blockers: List[str] = []
    if not lineage_reference_pass:
        blockers.append("FROZEN_PREDECESSOR_LINEAGE_IDENTITY_INVALID")
    if not static_launch_safety_pass:
        blockers.append("CAMERA_ONLY_STATIC_LAUNCH_SAFETY_NOT_VALIDATED")
    if toolchain.get("validated_pass") is not True:
        blockers.append("ROS1_NOETIC_TOOLCHAIN_NOT_AVAILABLE")
    blockers.extend((
        "ROS1_NOETIC_BUILD_INSTALL_NOT_VERIFIED",
        "ROS1_FORMAL_FOUR_SCENE_EVIDENCE_MISSING",
        "ROS1_FORMAL_TF_3D_NOT_VALIDATED",
        "ROS1_FORMAL_LATENCY_NOT_VALIDATED",
    ))
    return {
        "schema_version": SCHEMA_VERSION,
        "preflight_id": PREFLIGHT_ID,
        "mode": "PRODUCTION_STATIC_CAMERA_ONLY_PREFLIGHT",
        "read_only": True,
        "inspection_only": True,
        "starts_ros_graph": False,
        "starts_camera": False,
        "runs_inference": False,
        "records_rosbag": False,
        "publishes_ros_messages": False,
        "publishes_control_messages": False,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "formal_consumer": False,
        "formal_acceptance": False,
        "formal_four_scene_frame_denominator": 0,
        "formal_tf_pass": False,
        "formal_3d_pass": False,
        "formal_latency_pass": False,
        "delivery_ready": False,
        "lineage_reference_pass": lineage_reference_pass,
        "static_launch_safety_pass": static_launch_safety_pass,
        "static_preflight_ready_for_manual_camera_only_stage": preflight_pass,
        "preflight_pass": preflight_pass,
        "predecessor_authority_v4": predecessor,
        "frozen_predecessor_references": {
            "canonical_v5": canonical,
            "report_v4": report,
        },
        "launch_admission": {
            "dabai_archive_reference": dabai,
            "actual_vendor_launch": live,
            "formal_detector": formal,
        },
        "toolchain": toolchain,
        "blockers": sorted(set(blockers)),
        "failures": failures,
    }


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Static ROS1/Noetic camera-only preflight; never starts ROS or a camera."
        ))
    parser.add_argument(
        "--actual-vendor-launch",
        required=True,
        type=Path,
        help=(
            "Absolute live dabai_u3.launch path that will be passed unchanged "
            "to roslaunch after this inert static check."),
    )
    return parser.parse_args(args)


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False)


def main(args: Optional[Sequence[str]] = None) -> int:
    options = parse_args(args)
    try:
        # The production CLI always audits the current OS root.  Alternate
        # roots exist only as a direct pure-function seam for unit tests and
        # cannot be selected by a production caller.
        result = evaluate_preflight(
            environment_root=Path("/"),
            actual_vendor_launch=options.actual_vendor_launch)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "preflight_id": PREFLIGHT_ID,
            "mode": "PRODUCTION_STATIC_CAMERA_ONLY_PREFLIGHT",
            "read_only": True,
            "inspection_only": True,
            "starts_ros_graph": False,
            "starts_camera": False,
            "runs_inference": False,
            "records_rosbag": False,
            "publishes_ros_messages": False,
            "publishes_control_messages": False,
            "authorizes_motion": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_field_evidence_consumer": False,
            "formal_consumer": False,
            "formal_acceptance": False,
            "formal_four_scene_frame_denominator": 0,
            "formal_tf_pass": False,
            "formal_3d_pass": False,
            "formal_latency_pass": False,
            "delivery_ready": False,
            "static_preflight_ready_for_manual_camera_only_stage": False,
            "preflight_pass": False,
            "blockers": ["ROS1_CAMERA_ONLY_STATIC_PREFLIGHT_INTERNAL_FAILURE"],
            "failures": ["preflight_internal_failure:" + type(error).__name__],
        }
    sys.stdout.write(MARKER + _encode(result) + "\n")
    return 0 if result.get("preflight_pass") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())
