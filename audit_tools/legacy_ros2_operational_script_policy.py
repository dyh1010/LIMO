"""Static, fail-closed policy for demoted legacy ROS2 operational scripts.

The validator reads files only.  It never invokes a shell, sources ROS,
queries a graph or device, and cannot authorize field execution.  The two
ROS1/Noetic bridge scripts are path-exact exceptions to the generic legacy
ROS2 guard; their existing one-time authorization and zero-chain controls
remain outside this inventory's authority.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_RELATIVE_PATH = Path(
    "audit_tools/legacy_ros2_operational_script_inventory.json"
)

ACTIVE_LEGACY = {
    "scripts/smoke_test_touch_only.sh": {
        "domain": 221,
        "topic": None,
        "launch_file": "cleanup_system.launch.py",
        "node_list_count": 1,
        "python_probe": "scripts/touch_only_smoke_probe.py",
        "topic_bindings": {
            "base_output_topic": (
                "/test/legacy_ros2_offline/touch_only/base_output"
            ),
        },
        "safety_arguments": (
            "use_tracked_base_controller:=false",
            "allow_base_motion:=false",
            "use_real_perception:=false",
            "use_mock_perception:=true",
            "use_mock_executor:=true",
            "executor_dry_run:=true",
            "use_gripper_controller:=false",
            "allow_arm_motion:=false",
        ),
    },
    "scripts/smoke_test_tracked_zero_launch.sh": {
        "domain": 222,
        "topic": "/test/cleanup/tracked_zero_output",
        "launch_file": "tracked_base_zero_output.launch.py",
        "node_list_count": 1,
        "python_probe": "scripts/smoke_test_tracked_zero_launch.py",
        "topic_bindings": {
            "input_topic": (
                "/test/legacy_ros2_offline/tracked_zero_launch/request"
            ),
            "output_topic": "/test/cleanup/tracked_zero_output",
            "authorization_topic": (
                "/test/legacy_ros2_offline/tracked_zero_launch/authorized"
            ),
            "safety_topic": (
                "/test/legacy_ros2_offline/tracked_zero_launch/safety"
            ),
            "topology_ready_topic": (
                "/test/legacy_ros2_offline/tracked_zero_launch/topology_ready"
            ),
        },
        "safety_arguments": (),
    },
    "scripts/smoke_test_tracked_zero_guard.sh": {
        "domain": 223,
        "topic": "/test/cleanup/tracked_zero_output",
        "launch_file": "tracked_base_zero_output.launch.py",
        "node_list_count": 0,
        "python_probe": "scripts/verify_tracked_zero_output.py",
        "topic_bindings": {
            "input_topic": (
                "/test/legacy_ros2_offline/tracked_zero_guard/request"
            ),
            "output_topic": "/test/cleanup/tracked_zero_output",
            "authorization_topic": (
                "/test/legacy_ros2_offline/tracked_zero_guard/authorized"
            ),
            "safety_topic": (
                "/test/legacy_ros2_offline/tracked_zero_guard/safety"
            ),
            "topology_ready_topic": (
                "/test/legacy_ros2_offline/tracked_zero_guard/topology_ready"
            ),
        },
        "safety_arguments": (),
    },
}

RETIRED_LEGACY = (
    "scripts/tracked_base_stage2_preflight.sh",
    "scripts/robot_tracked_readonly_audit.sh",
)

BRIDGE_ALLOWLIST = (
    "scripts/ros1_base_bridge_preflight.sh",
    "scripts/run_ros1_base_bridge_zero_stage.sh",
)

COMPANION_PATHS = (
    "src/limo_cleanup_bringup/launch/tracked_base_zero_output.launch.py",
    "scripts/smoke_test_tracked_zero_launch.py",
    "scripts/verify_tracked_zero_output.py",
    "scripts/touch_only_smoke_probe.py",
    "src/limo_cleanup_bringup/launch/cleanup_system.launch.py",
)

PRODUCTION_ZERO_LAUNCH_TOPICS = {
    "input_topic": "/cleanup/base/cmd_vel_request",
    "output_topic": "/cleanup/base/safe_cmd_vel",
    "authorization_topic": "/cleanup/base/motion_authorized",
    "safety_topic": "/cleanup/base/safety_clear",
    "topology_ready_topic": "/cleanup/navigation/topology_ready",
}

PRODUCTION_PRIVATE_TOPIC_LITERALS = tuple(
    PRODUCTION_ZERO_LAUNCH_TOPICS.values())

EXPECTED_ARTIFACT_IDENTITIES = {
    "scripts/smoke_test_touch_only.sh": {
        "size_bytes": 5428,
        "sha256": "dbe6eeb1eb812d38b7f90eaf3663209b65ff7e18faabd24d744ddd3ac4de711d",
    },
    "scripts/tracked_base_stage2_preflight.sh": {
        "size_bytes": 476,
        "sha256": "ae370a8c4acd631100ea0a27d4b773a54e8323f9e4a29b976095637c2cb3dcc6",
    },
    "scripts/robot_tracked_readonly_audit.sh": {
        "size_bytes": 457,
        "sha256": "de74309d2a22f5c13eb2454d9d64eaa00cb904ae5143354210e488df1415285f",
    },
    "scripts/smoke_test_tracked_zero_launch.sh": {
        "size_bytes": 4714,
        "sha256": "d7b5888248f5b762cbe6f8070f16b6ba9c5ddd7bb046c158eec55c3840750605",
    },
    "scripts/smoke_test_tracked_zero_guard.sh": {
        "size_bytes": 4734,
        "sha256": "168755413c578c10d85ed334c0d7e4cf1694f8029c20edb7e173ccb90503e61d",
    },
    "scripts/ros1_base_bridge_preflight.sh": {
        "size_bytes": 14042,
        "sha256": "44990908ad2c60724ce12d5e103e4074c8a513c9a0ca7cbb017e82cf2328ec96",
    },
    "scripts/run_ros1_base_bridge_zero_stage.sh": {
        "size_bytes": 19045,
        "sha256": "19bd961ca37e6550dd789df1653c98ec8c36b103b7a196ab82a9aac680677f5d",
    },
    "src/limo_cleanup_bringup/launch/tracked_base_zero_output.launch.py": {
        "size_bytes": 2785,
        "sha256": "9bb7328e9bb68b974a16e18e977869fc2691145a405ac4814e5ad74e961d012e",
    },
    "scripts/smoke_test_tracked_zero_launch.py": {
        "size_bytes": 3016,
        "sha256": "a4e5efc4dcdba57c623bb81d85a20884a08e740ca2fe9a1c46545916fd1ef060",
    },
    "scripts/verify_tracked_zero_output.py": {
        "size_bytes": 6958,
        "sha256": "f72950492e42762c7fba55bf0c16c078b3d3f20652d4998d93927ff3cb9068dd",
    },
    "scripts/touch_only_smoke_probe.py": {
        "size_bytes": 4469,
        "sha256": "82256195cf9a08756004aeb5c7768020a8b4f9f28339a2586ca96bdfaf72d801",
    },
    "src/limo_cleanup_bringup/launch/cleanup_system.launch.py": {
        "size_bytes": 13231,
        "sha256": "9d9d7120e0eea57170d4ba2f559db455ef0fd578da022dc10d331340e07b3e22",
    },
}

LEGACY_PATHS = tuple(
    path
    for path in (
        "scripts/smoke_test_touch_only.sh",
        "scripts/tracked_base_stage2_preflight.sh",
        "scripts/robot_tracked_readonly_audit.sh",
        "scripts/smoke_test_tracked_zero_launch.sh",
        "scripts/smoke_test_tracked_zero_guard.sh",
    )
)

REQUIRED_MARKERS = (
    "FIELD_RUNTIME_AUTHORITY=ROS1_NOETIC",
    "LEGACY_ROS2_OFFLINE_ONLY",
    "NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE",
)

GUARD_PATTERN = re.compile(
    r"if\s+\[\[\s+[\"']?\$\{LIMO_ALLOW_LEGACY_ROS2_OFFLINE(?::-|-)\}"
    r"[\"']?\s+!=\s+[\"']1[\"']\s+\]\];\s*then"
)

PASS_DEMOTION_PATTERN = re.compile(
    r"LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS[^\n]*\n"
    r"[^\n]*NOT_NOETIC_FIELD_OR_DELIVERY_EVIDENCE"
)

PRE_GUARD_OPERATION_PATTERNS = (
    re.compile(r"(^|[;&|]\s*)(source|\.)\s+", re.MULTILINE),
    re.compile(r"(^|[;&|]\s*)ros2(?:\s|$)", re.MULTILINE),
    re.compile(r"(^|[;&|]\s*)python(?:3)?(?:\s|$)", re.MULTILINE),
    re.compile(
        r"(^|[;&|]\s*)(roscore|roslaunch|rosrun|rosnode|rostopic)(?:\s|$)",
        re.MULTILINE,
    ),
    re.compile(r"(^|[;&|]\s*)(fuser|udevadm)(?:\s|$)", re.MULTILINE),
    re.compile(r"/dev/(?:tty|limo)"),
)

FORBIDDEN_ACTIVE_TOKENS = (
    "/dev/tty",
    "/dev/limo",
    "ttyTHS",
    "ttyUSB",
    "ttyACM",
    "udevadm ",
    "fuser ",
    "ros2 topic pub",
    "ros2 action send_goal",
    "ros2 service call",
    "ros2 run limo_base",
    "ros2 launch limo_base",
    "tracked_base_vendor_stage2.launch.py",
    "limo_ros2_ws",
    "/home/agilex/",
    "allow_base_motion:=true",
    "allow_arm_motion:=true",
    "use_gripper_controller:=true",
    "allow_gripper_motion:=true",
    "use_real_perception:=true",
    "use_tracked_base_controller:=true",
)

FORBIDDEN_PRODUCTION_TOPICS = (
    "/cmd_vel",
    "/cleanup/base/cmd_vel_request",
    "/cleanup/base/safe_cmd_vel",
    "/cleanup/base/driver_cmd_vel",
    "/cmd_vel_nav",
    "/cmd_vel_teleop",
    "/limo/vel_cmd",
    "/camera/",
)

REQUIRED_ISOLATION_TOKENS = (
    "ROS_DISCOVERY_SERVER",
    "FASTRTPS_DEFAULT_PROFILES_FILE",
    "FASTDDS_DEFAULT_PROFILES_FILE",
)

RETIRED_FORBIDDEN_PATTERNS = (
    re.compile(r"(^|[;&|]\s*)(source|\.)\s+", re.MULTILINE),
    re.compile(r"(^|[;&|]\s*)ros2(?:\s|$)", re.MULTILINE),
    re.compile(r"(^|[;&|]\s*)python(?:3)?(?:\s|$)", re.MULTILINE),
    re.compile(
        r"(^|[;&|]\s*)(fuser|udevadm|ls|readlink)(?:\s|$)", re.MULTILINE),
    re.compile(r"/(?:dev|sys|proc)/"),
)


def _expected_inventory() -> Mapping[str, Any]:
    legacy_entries = []
    for path in LEGACY_PATHS:
        if path in ACTIVE_LEGACY:
            policy = ACTIVE_LEGACY[path]
            legacy_entries.append({
                "path": path,
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[path],
                "mode": "LEGACY_ROS2_OFFLINE_MOCK_ZERO_ONLY",
                "offline_execution_permitted": True,
                "ros_localhost_only": 1,
                "ros_domain_id": policy["domain"],
                "required_test_topic": policy["topic"],
                "required_topic_bindings": policy["topic_bindings"],
                "allowed_ros2_cli_operations": [
                    "launch:limo_cleanup_bringup/" + policy["launch_file"],
                    *(["node:list"] if policy["node_list_count"] else []),
                ],
                "allowed_python_probe": policy["python_probe"],
                "hardware_or_vendor_access_permitted": False,
                "field_or_delivery_evidence": False,
            })
        else:
            legacy_entries.append({
                "path": path,
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[path],
                "mode": "RETIRED_FAIL_CLOSED_SHIM",
                "offline_execution_permitted": False,
                "ros_localhost_only": None,
                "ros_domain_id": None,
                "required_test_topic": None,
                "required_topic_bindings": {},
                "allowed_ros2_cli_operations": [],
                "allowed_python_probe": None,
                "hardware_or_vendor_access_permitted": False,
                "field_or_delivery_evidence": False,
            })
    return {
        "schema_version": "limo_legacy_ros2_operational_script_inventory/v1",
        "inventory_id": "legacy-ros2-operational-script-demotion-20260815-v1",
        "field_runtime_authority": {
            "ros_version": "ROS1",
            "ros_distro": "Noetic",
            "authority_label": "ROS1_NOETIC",
            "legacy_ros2_is_field_authority": False,
            "historical_mock_pass_is_noetic_evidence": False,
            "historical_mock_pass_is_field_evidence": False,
            "historical_mock_pass_is_delivery_evidence": False,
        },
        "safety_boundary": {
            "read_only_inventory": True,
            "authorizes_ros_start": False,
            "authorizes_hardware_access": False,
            "authorizes_motion": False,
            "authorizes_goal": False,
            "authorizes_nonzero_twist": False,
            "authorizes_recovery": False,
            "release_pin_may_be_updated": False,
        },
        "legacy_guard": {
            "environment_variable": "LIMO_ALLOW_LEGACY_ROS2_OFFLINE",
            "only_accepted_value": "1",
            "default_exit_code": 64,
            "rejected_examples": ["UNSET", "", "0", "true"],
            "required_markers": list(REQUIRED_MARKERS),
        },
        "legacy_ros2_scripts": legacy_entries,
        "ros1_bridge_allowlist": [
            {
                "path": path,
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[path],
                "mode": "ROS1_NOETIC_TO_ROS2_BRIDGE_EXCEPTION",
                "generic_legacy_guard_applies": False,
                "field_execution_authorized_by_inventory": False,
                "requires_existing_one_time_authorization_boundary": True,
                "zero_chain_required": True,
                "release_blockers_unchanged": True,
            }
            for path in BRIDGE_ALLOWLIST
        ],
        "companion_static_contracts": [
            {
                "path": COMPANION_PATHS[0],
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[
                    COMPANION_PATHS[0]],
                "role": "PRODUCTION_BRIDGE_DEFAULT_ZERO_OUTPUT_LAUNCH",
                "execution_authorized_by_inventory": False,
                "offline_legacy_shells_must_override_all_five_topics": True,
                "allow_base_motion_must_be_literal_false": True,
            },
            {
                "path": COMPANION_PATHS[1],
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[
                    COMPANION_PATHS[1]],
                "role": "LEGACY_OFFLINE_TEST_TOPIC_ZERO_LATCH_PROBE",
                "execution_authorized_by_inventory": False,
                "publishers_must_be_test_topics_only": True,
                "field_or_delivery_evidence": False,
            },
            {
                "path": COMPANION_PATHS[2],
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[
                    COMPANION_PATHS[2]],
                "role": "LEGACY_OFFLINE_TEST_TOPIC_READ_ONLY_VERIFIER",
                "execution_authorized_by_inventory": False,
                "publisher_count": 0,
                "field_or_delivery_evidence": False,
            },
            {
                "path": COMPANION_PATHS[3],
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[
                    COMPANION_PATHS[3]],
                "role": "LEGACY_OFFLINE_ORDINARY_MOCK_INTENT_PROBE",
                "execution_authorized_by_inventory": False,
                "motion_command_publishers_permitted": False,
                "field_or_delivery_evidence": False,
            },
            {
                "path": COMPANION_PATHS[4],
                "static_contract_identity": EXPECTED_ARTIFACT_IDENTITIES[
                    COMPANION_PATHS[4]],
                "role": "LEGACY_TOUCH_MOCK_SYSTEM_SOURCE_LAUNCH_DEPENDENCY",
                "execution_authorized_by_inventory": False,
                "safe_defaults_must_remain_fail_closed": True,
                "field_or_delivery_evidence": False,
            },
        ],
        "runtime_resolution_boundary": {
            "source_tree_contract_only": True,
            "installed_runtime_resolution_verified": False,
            "runtime_execution_ready": False,
            "unresolved_runtime_bindings": [
                "ros2_pkg_prefix_and_installed_launch_identity_not_checked",
            ],
        },
        "bridge_exception_policy": {
            "path_exact": True,
            "content_copy_does_not_inherit_exception": True,
            "generic_legacy_ros2_guard_must_not_be_added": True,
            "bridge_all_topics_forbidden": True,
            "existing_authorization_and_zero_chain_controls_must_not_be_weakened": True,
        },
    }


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("nonfinite_json_number:" + value)


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite,
    )


def _safe_relative_path(value: str) -> Optional[str]:
    if not isinstance(value, str) or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
            part in ("", ".", "..") for part in path.parts):
        return None
    return path.as_posix()


def classify_operational_script(relative_path: str) -> str:
    """Classify by exact repository path; source bytes never grant an exception."""
    safe = _safe_relative_path(relative_path)
    if safe in ACTIVE_LEGACY:
        return "LEGACY_ROS2_OFFLINE_MOCK_ZERO_ONLY"
    if safe in RETIRED_LEGACY:
        return "RETIRED_FAIL_CLOSED_SHIM"
    if safe in BRIDGE_ALLOWLIST:
        return "ROS1_NOETIC_TO_ROS2_BRIDGE_EXCEPTION"
    return "UNLISTED_OPERATIONAL_SCRIPT_REJECTED"


def _shell_lines(source: str) -> Sequence[Tuple[int, str]]:
    result = []
    offset = 0
    for raw in source.splitlines(True):
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            result.append((offset, stripped))
        offset += len(raw)
    return result


def _executable_text(source: str) -> str:
    return "\n".join(line for _, line in _shell_lines(source))


def _has_operation_before_guard(source: str, guard_start: int) -> bool:
    for offset, line in _shell_lines(source):
        if offset >= guard_start:
            break
        if any(pattern.search(line) for pattern in PRE_GUARD_OPERATION_PATTERNS):
            return True
    return False


def _validate_common_legacy(path: str, source: str) -> List[str]:
    failures = []
    if not source.startswith("#!/usr/bin/env bash\n"):
        failures.append(path + ":invalid_or_missing_bash_shebang")
    for marker in REQUIRED_MARKERS:
        if marker not in source:
            failures.append(path + ":missing_marker:" + marker)
    if "LIMO_ALLOW_LEGACY_ROS2_OFFLINE" not in source:
        failures.append(path + ":missing_legacy_opt_in_name")
    return failures


def _validate_guard(path: str, source: str) -> List[str]:
    failures = []
    guards = list(GUARD_PATTERN.finditer(source))
    if len(guards) != 1:
        failures.append(path + ":exact_opt_in_guard_count_not_one")
        return failures
    guard = guards[0]
    block_end = source.find("\nfi", guard.end())
    guard_block = source[guard.end():block_end] if block_end >= 0 else ""
    exits_64 = "exit 64" in guard_block
    exits_named_64 = (
        "readonly LEGACY_EXIT=64" in source[:guard.start()]
        and 'exit "${LEGACY_EXIT}"' in guard_block
    )
    if block_end < 0 or not (exits_64 or exits_named_64):
        failures.append(path + ":guard_does_not_exit_64")
    if _has_operation_before_guard(source, guard.start()):
        failures.append(path + ":guard_occurs_after_operational_command")
    return failures


def _fixed_shell_constants(executable: str) -> Mapping[str, str]:
    constants: Dict[str, str] = {}
    pattern = re.compile(
        r"^(?:readonly\s+)?([A-Z][A-Z0-9_]*)=(?:[\"']([^\"']*)[\"']|([^\s]+))$",
        re.MULTILINE,
    )
    for match in pattern.finditer(executable):
        constants[match.group(1)] = (
            match.group(2) if match.group(2) is not None else match.group(3)
        )
    return constants


def _expand_fixed_shell_value(value: str, constants: Mapping[str, str]) -> str:
    variable = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
    previous = None
    while value != previous:
        previous = value
        value = variable.sub(
            lambda match: constants.get(match.group(1), match.group(0)), value)
    return value


def _topic_bindings(executable: str) -> Tuple[Mapping[str, str], bool]:
    constants = _fixed_shell_constants(executable)
    bindings: Dict[str, str] = {}
    duplicate = False
    pattern = re.compile(
        r"\b([a-z][a-z0-9_]*topic):=(?:[\"']([^\"']+)[\"']|([^\s\\]+))"
    )
    for match in pattern.finditer(executable):
        name = match.group(1)
        raw = match.group(2) if match.group(2) is not None else match.group(3)
        value = _expand_fixed_shell_value(raw, constants)
        if name in bindings:
            duplicate = True
        bindings[name] = value
    return bindings, duplicate


def _validate_active(path: str, source: str) -> List[str]:
    failures = _validate_common_legacy(path, source)
    failures.extend(_validate_guard(path, source))
    policy = ACTIVE_LEGACY[path]
    executable = _executable_text(source)
    required_localhost = "export ROS_LOCALHOST_ONLY=1"
    required_domain = "export ROS_DOMAIN_ID={}".format(policy["domain"])
    if required_localhost not in executable:
        failures.append(path + ":localhost_only_not_fixed_to_one")
    if required_domain not in executable:
        failures.append(path + ":dedicated_domain_not_fixed")
    if "ROS_LOCALHOST_ONLY=0" in executable:
        failures.append(path + ":global_discovery_enabled")
    if re.search(r"(?:export\s+)?ROS_DOMAIN_ID=(?:[\"']?)137(?:[\"']?)(?:\s|$)",
                 executable):
        failures.append(path + ":shared_domain_137_enabled")
    if any(token in executable for token in FORBIDDEN_ACTIVE_TOKENS):
        failures.append(path + ":hardware_real_or_command_token_present")
    if any(topic in executable for topic in FORBIDDEN_PRODUCTION_TOPICS):
        failures.append(path + ":production_command_topic_present")
    if any(token in executable for token in ("${1", "${2", "$1", "$2")):
        failures.append(path + ":positional_override_surface_present")
    if not re.search(r"if\s+\[\[\s+[\"']?\$#[\"']?\s+-ne\s+0\s+\]\]",
                     executable):
        failures.append(path + ":command_line_override_rejection_missing")
    for token in REQUIRED_ISOLATION_TOKENS:
        if token not in executable:
            failures.append(path + ":isolation_override_rejection_missing:" + token)
    for variable in ("ROS_LOCALHOST_ONLY", "ROS_DOMAIN_ID"):
        if not re.search(
                r"if\s+\[\[\s+-v\s+" + variable + r"\b", executable):
            failures.append(
                path + ":ambient_fixed_value_rejection_missing:" + variable)
    for argument in policy["safety_arguments"]:
        if argument not in executable:
            failures.append(path + ":missing_fixed_safety_argument:" + argument)
    bindings, duplicate_binding = _topic_bindings(executable)
    if duplicate_binding:
        failures.append(path + ":duplicate_topic_binding")
    if bindings != policy["topic_bindings"]:
        failures.append(path + ":topic_bindings_not_exact_test_only_set")
    if any(not value.startswith("/test/") for value in bindings.values()):
        failures.append(path + ":non_test_topic_binding")
    ros2_commands = re.findall(r"\bros2\s+([a-z0-9_-]+)", executable)
    if any(command not in ("launch", "node") for command in ros2_commands):
        failures.append(path + ":unapproved_ros2_cli_operation")
    if re.search(r"\bros2\s+node\b", executable) and not re.search(
            r"\bros2\s+node\s+list\b", executable):
        failures.append(path + ":unapproved_ros2_node_operation")
    if len(re.findall(r"\bros2\s+launch\b", executable)) != 1:
        failures.append(path + ":ros2_launch_count_not_one")
    if len(re.findall(r"\bros2\s+node\s+list\b", executable)) != (
            policy["node_list_count"]):
        failures.append(path + ":ros2_node_list_count_mismatch")
    if "limo_cleanup_bringup" not in executable or (
            policy["launch_file"] not in executable):
        failures.append(path + ":fixed_mock_launch_target_missing")
    if len(re.findall(r"\bpython3\s+", executable)) != 1 or (
            PurePosixPath(policy["python_probe"]).name not in executable):
        failures.append(path + ":fixed_python_probe_contract_mismatch")
    if not PASS_DEMOTION_PATTERN.search(source):
        failures.append(path + ":mock_pass_not_immediately_demoted")
    if "PASS:" in executable and "LEGACY_ROS2_OFFLINE_ONLY_MOCK_PASS" not in executable:
        failures.append(path + ":undemoted_generic_pass_marker")
    return failures


def _validate_retired(path: str, source: str) -> List[str]:
    failures = _validate_common_legacy(path, source)
    failures.extend(_validate_guard(path, source))
    executable = _executable_text(source)
    if any(pattern.search(executable) for pattern in RETIRED_FORBIDDEN_PATTERNS):
        failures.append(path + ":retired_shim_contains_ros_or_device_operation")
    exit_values = re.findall(
        r"(?:^|[;&|]\s*)exit\s+([0-9]+)(?:\s|$)",
        executable,
        flags=re.MULTILINE,
    )
    if not exit_values or any(value != "64" for value in exit_values):
        failures.append(path + ":retired_shim_contains_non64_exit")
    guards = list(GUARD_PATTERN.finditer(source))
    guard_end = source.find("\nfi", guards[0].end()) if len(guards) == 1 else -1
    if guard_end < 0 or not re.search(
            r"(?:^|\n)exit\s+64(?:\s|$)", source[guard_end + 3:]):
        failures.append(path + ":retired_shim_lacks_unconditional_exit_64")
    if re.search(r"\b(elif|else|case|while|until|for)\b", executable):
        failures.append(path + ":retired_shim_contains_extra_control_flow")
    return failures


def _validate_bridge(path: str, source: str) -> List[str]:
    failures = []
    if "LEGACY_ROS2_OFFLINE_ONLY" in source or (
            "LIMO_ALLOW_LEGACY_ROS2_OFFLINE" in source):
        failures.append(path + ":generic_legacy_guard_applied_to_bridge_exception")
    if "--bridge-all-topics" in source:
        failures.append(path + ":bridge_all_topics_forbidden")
    if "ROS1" not in source or "noetic" not in source.lower():
        failures.append(path + ":ros1_noetic_authority_not_declared")
    required = {
        "scripts/ros1_base_bridge_preflight.sh": (
            "ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE",
            "ROS1_BASE_BRIDGE_PREFLIGHT_BLOCKED",
            "limo_start_private_cmd.launch",
        ),
        "scripts/run_ros1_base_bridge_zero_stage.sh": (
            "ROS1_BASE_ZERO_STAGE_AUTHORIZATION_FILE",
            "consume_one_time_authorization",
            "ros1_base_bridge_preflight.sh",
            "Only zero commands are admitted. Nonzero motion remains disabled.",
        ),
    }
    for token in required[path]:
        if token not in source:
            failures.append(path + ":bridge_control_missing:" + token)
    return failures


def _call_name(call: ast.Call) -> Optional[str]:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _string_constants(tree: ast.AST) -> Sequence[str]:
    return tuple(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _fixed_string_assignments(
        tree: ast.AST) -> Tuple[Mapping[str, str], Sequence[str]]:
    assignments: Dict[str, str] = {}

    def resolve(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return assignments.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = resolve(node.left)
            right = resolve(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    pending = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.isupper()
    ]
    counts: Dict[str, int] = {}
    for node in pending:
        name = node.targets[0].id
        counts[name] = counts.get(name, 0) + 1
    duplicates = tuple(sorted(
        name for name, count in counts.items() if count != 1))
    pending = [
        node for node in pending if node.targets[0].id not in duplicates]
    changed = True
    remaining_passes = len(pending) + 1
    while changed and remaining_passes > 0:
        changed = False
        remaining_passes -= 1
        for node in pending:
            name = node.targets[0].id
            value = resolve(node.value)
            if value is not None and assignments.get(name) != value:
                assignments[name] = value
                changed = True
    return assignments, duplicates


def _resolved_topic_argument(
        call: ast.Call, assignments: Mapping[str, str]) -> Optional[str]:
    if len(call.args) < 2:
        return None
    node = call.args[1]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return assignments.get(node.id)
    return None


def _validate_zero_launch_companion(path: str, source: str) -> List[str]:
    failures = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [path + ":python_ast_parse_failed"]
    declarations: Dict[str, str] = {}
    declaration_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != (
                "DeclareLaunchArgument"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or (
                not isinstance(node.args[0].value, str)):
            failures.append(path + ":dynamic_launch_argument_name")
            continue
        name = node.args[0].value
        default = None
        for keyword in node.keywords:
            if keyword.arg == "default_value" and isinstance(
                    keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, str):
                default = keyword.value.value
        if default is None:
            failures.append(path + ":dynamic_or_missing_launch_default:" + name)
            continue
        declaration_count += 1
        if name in declarations:
            failures.append(path + ":duplicate_launch_argument:" + name)
        declarations[name] = default
    topic_declarations = {
        name: value for name, value in declarations.items()
        if name.endswith("_topic")
    }
    if topic_declarations != PRODUCTION_ZERO_LAUNCH_TOPICS:
        failures.append(path + ":production_topic_defaults_changed")
    if declaration_count != 6 or declarations.get("publish_rate") != "20.0":
        failures.append(path + ":launch_argument_set_not_exact")
    allow_values = []
    parameter_topic_names = set()
    all_parameter_topic_names = set()
    node_targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "Node":
            package = None
            executable = None
            for keyword in node.keywords:
                if keyword.arg == "package" and isinstance(
                        keyword.value, ast.Constant):
                    package = keyword.value.value
                elif keyword.arg == "executable" and isinstance(
                        keyword.value, ast.Constant):
                    executable = keyword.value.value
            node_targets.append((package, executable))
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(
                    key.value, str):
                continue
            if key.value == "allow_base_motion":
                allow_values.append(value)
            if key.value.endswith("_topic"):
                all_parameter_topic_names.add(key.value)
            if key.value in PRODUCTION_ZERO_LAUNCH_TOPICS:
                if isinstance(value, ast.Name) and value.id == key.value:
                    parameter_topic_names.add(key.value)
    if len(allow_values) != 1 or not isinstance(
            allow_values[0], ast.Constant) or allow_values[0].value is not False:
        failures.append(path + ":allow_base_motion_not_literal_false")
    if parameter_topic_names != set(PRODUCTION_ZERO_LAUNCH_TOPICS):
        failures.append(path + ":five_topic_parameters_not_forwarded_exactly")
    if all_parameter_topic_names != set(PRODUCTION_ZERO_LAUNCH_TOPICS):
        failures.append(path + ":extra_or_missing_topic_parameter")
    if node_targets != [("limo_cleanup_base", "tracked_base_controller")]:
        failures.append(path + ":node_target_set_not_exact_zero_controller")
    constants = _string_constants(tree)
    if "limo_cleanup_base" not in constants or (
            "tracked_base_controller" not in constants):
        failures.append(path + ":zero_controller_target_changed")
    return failures


def _validate_zero_probe_companion(path: str, source: str) -> List[str]:
    failures = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [path + ":python_ast_parse_failed"]
    assignments, duplicate_constants = _fixed_string_assignments(tree)
    if duplicate_constants:
        failures.append(path + ":duplicate_fixed_topic_constant")
    expected_publishers = (
        "/test/legacy_ros2_offline/tracked_zero_launch/request",
        "/test/legacy_ros2_offline/tracked_zero_launch/authorized",
        "/test/legacy_ros2_offline/tracked_zero_launch/safety",
    )
    publisher_topics = []
    subscriber_topics = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "create_publisher":
            publisher_topics.append(_resolved_topic_argument(node, assignments))
        elif name == "create_subscription":
            subscriber_topics.append(_resolved_topic_argument(node, assignments))
        elif name in ("create_client", "create_service", "ActionClient"):
            failures.append(path + ":service_or_action_client_forbidden")
    if tuple(publisher_topics) != expected_publishers or any(
            topic is None or not topic.startswith("/test/")
            for topic in publisher_topics):
        failures.append(path + ":publisher_topics_not_exact_test_only_set")
    if subscriber_topics != ["/test/cleanup/tracked_zero_output"]:
        failures.append(path + ":output_subscription_not_fixed_test_topic")
    constants = _string_constants(tree)
    if any(topic in constants for topic in PRODUCTION_PRIVATE_TOPIC_LITERALS):
        failures.append(path + ":production_private_topic_literal_present")
    if "LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK" not in source:
        failures.append(path + ":legacy_mock_check_marker_missing")
    return failures


def _validate_zero_verifier_companion(path: str, source: str) -> List[str]:
    failures = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [path + ":python_ast_parse_failed"]
    assignments, duplicate_constants = _fixed_string_assignments(tree)
    if duplicate_constants:
        failures.append(path + ":duplicate_fixed_topic_constant")
    if assignments.get("SAFE_COMMAND_TOPIC") != (
            "/test/cleanup/tracked_zero_output"):
        failures.append(path + ":safe_command_topic_not_fixed_test_topic")
    publisher_count = 0
    subscription_topics = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "create_publisher" or name == "publish":
            publisher_count += 1
        elif name == "create_subscription":
            subscription_topics.append(
                _resolved_topic_argument(node, assignments))
        elif name in ("create_client", "create_service", "ActionClient"):
            failures.append(path + ":service_or_action_client_forbidden")
    if publisher_count != 0:
        failures.append(path + ":verifier_contains_publisher")
    if subscription_topics != ["/test/cleanup/tracked_zero_output"]:
        failures.append(path + ":verifier_subscription_not_exact")
    return failures


def _validate_touch_probe_companion(path: str, source: str) -> List[str]:
    failures = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [path + ":python_ast_parse_failed"]
    assignments, duplicate_constants = _fixed_string_assignments(tree)
    if duplicate_constants:
        failures.append(path + ":duplicate_fixed_topic_constant")
    publisher_calls = []
    subscriber_topics = []
    publish_call_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "create_publisher":
            message_name = (
                node.args[0].id if node.args and isinstance(node.args[0], ast.Name)
                else None
            )
            publisher_calls.append(
                (message_name, _resolved_topic_argument(node, assignments)))
        elif name == "create_subscription":
            subscriber_topics.append(_resolved_topic_argument(node, assignments))
        elif name == "publish":
            publish_call_count += 1
        elif name in ("create_client", "create_service", "ActionClient"):
            failures.append(path + ":service_or_action_client_forbidden")
    if publisher_calls != [("String", "/cleanup/command_text")]:
        failures.append(path + ":touch_probe_not_single_ordinary_text_intent")
    if subscriber_topics != ["/cleanup/task", "/cleanup/status"]:
        failures.append(path + ":touch_probe_subscription_set_changed")
    if publish_call_count != 1:
        failures.append(path + ":touch_probe_publish_call_count_not_one")
    forbidden = (
        "Twist", "/cmd_vel", "/dev/", "goal", "ActionClient",
        "allow_base_motion", "allow_arm_motion", "gripper_controller",
    )
    if any(token in source for token in forbidden):
        failures.append(path + ":touch_probe_motion_or_hardware_token_present")
    if source.count("LEGACY_ROS2_OFFLINE_ONLY_MOCK_CHECK") < 1:
        failures.append(path + ":legacy_mock_check_marker_missing")
    if "task.action == 'touch_only'" not in source or "dry-run" not in source:
        failures.append(path + ":touch_only_dry_run_assertion_missing")
    return failures


def _validate_touch_launch_companion(path: str, source: str) -> List[str]:
    failures = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [path + ":python_ast_parse_failed"]
    defaults: Dict[str, str] = {}
    duplicate = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != (
                "DeclareLaunchArgument"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or (
                not isinstance(node.args[0].value, str)):
            failures.append(path + ":dynamic_launch_argument_name")
            continue
        name = node.args[0].value
        value = None
        for keyword in node.keywords:
            if keyword.arg == "default_value" and isinstance(
                    keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, str):
                value = keyword.value.value
        if value is not None:
            if name in defaults:
                duplicate = True
            defaults[name] = value
    required_defaults = {
        "use_mock_perception": "true",
        "use_real_perception": "false",
        "use_mock_executor": "true",
        "executor_dry_run": "true",
        "allow_arm_motion": "false",
        "use_gripper_controller": "false",
        "gripper_backend": "dry_run",
        "allow_gripper_motion": "false",
        "use_tracked_base_controller": "false",
        "allow_base_motion": "false",
    }
    if duplicate or any(
            defaults.get(name) != value
            for name, value in required_defaults.items()):
        failures.append(path + ":touch_launch_safe_defaults_changed")
    constants = _string_constants(tree)
    required_targets = (
        "mock_perception", "mock_executor", "task_manager", "language_node",
    )
    if any(target not in constants for target in required_targets):
        failures.append(path + ":touch_mock_pipeline_target_missing")
    return failures


def _validate_companion(path: str, source: str) -> List[str]:
    validators = {
        COMPANION_PATHS[0]: _validate_zero_launch_companion,
        COMPANION_PATHS[1]: _validate_zero_probe_companion,
        COMPANION_PATHS[2]: _validate_zero_verifier_companion,
        COMPANION_PATHS[3]: _validate_touch_probe_companion,
        COMPANION_PATHS[4]: _validate_touch_launch_companion,
    }
    return validators[path](path, source)


def validate_operational_script(relative_path: str, source: str) -> Mapping[str, Any]:
    """Validate one exact-path, exact-identity candidate fail-closed."""
    classification = classify_operational_script(relative_path)
    failures: List[str]
    if classification == "LEGACY_ROS2_OFFLINE_MOCK_ZERO_ONLY":
        failures = _validate_active(relative_path, source)
    elif classification == "RETIRED_FAIL_CLOSED_SHIM":
        failures = _validate_retired(relative_path, source)
    elif classification == "ROS1_NOETIC_TO_ROS2_BRIDGE_EXCEPTION":
        failures = _validate_bridge(relative_path, source)
    else:
        failures = [str(relative_path) + ":unlisted_operational_script"]
    identity_validated = False
    expected_identity = EXPECTED_ARTIFACT_IDENTITIES.get(relative_path)
    if expected_identity is not None:
        raw = source.encode("utf-8")
        actual_identity = {
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        identity_validated = actual_identity == expected_identity
        if not identity_validated:
            failures.append(
                relative_path + ":static_contract_identity_mismatch")
    return {
        "path": relative_path,
        "classification": classification,
        "identity_validated": identity_validated,
        "authoritative_static_gate": identity_validated and not failures,
        "validated_pass": not failures,
        "failures": sorted(set(failures)),
    }


def _read_regular_file(root: Path, relative_path: str) -> Tuple[bytes, Path]:
    root = root.resolve(strict=True)
    safe = _safe_relative_path(relative_path)
    if safe is None:
        raise OSError("unsafe_relative_path")
    path = root.joinpath(*PurePosixPath(safe).parts)
    if path.is_symlink() or not path.is_file():
        raise OSError("missing_or_nonregular_file")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    raw = resolved.read_bytes()
    if resolved.stat().st_size != len(raw):
        raise OSError("file_changed_during_read")
    return raw, resolved


def validate_workspace(
        workspace_root: Path = WORKSPACE_ROOT,
        inventory_payload: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Validate the fixed inventory and scripts without executing any script."""
    root = Path(workspace_root)
    failures: List[str] = []
    observed: List[Mapping[str, Any]] = []
    observed_companions: List[Mapping[str, Any]] = []
    if inventory_payload is None:
        try:
            raw, _ = _read_regular_file(
                root, INVENTORY_RELATIVE_PATH.as_posix())
            inventory_payload = _strict_json(raw)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            inventory_payload = None
            failures.append("inventory_read_or_parse_failed:" + type(error).__name__)
    if inventory_payload != _expected_inventory():
        failures.append("inventory_payload_mismatch")
    expected_paths = LEGACY_PATHS + BRIDGE_ALLOWLIST
    for relative_path in expected_paths:
        try:
            raw, _ = _read_regular_file(root, relative_path)
            source = raw.decode("utf-8")
            result = validate_operational_script(relative_path, source)
            actual_identity = {
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            identity_failure = []
            if actual_identity != EXPECTED_ARTIFACT_IDENTITIES[relative_path]:
                identity_failure.append(
                    relative_path + ":static_contract_identity_mismatch")
            script_failures = result["failures"] + identity_failure
            observed.append({
                "path": relative_path,
                "classification": result["classification"],
                **actual_identity,
                "validated_pass": not script_failures,
                "failures": sorted(set(script_failures)),
            })
            failures.extend(script_failures)
        except (OSError, UnicodeError) as error:
            failures.append(
                relative_path + ":read_failed:" + type(error).__name__)
    for relative_path in COMPANION_PATHS:
        try:
            raw, _ = _read_regular_file(root, relative_path)
            source = raw.decode("utf-8")
            companion_failures = _validate_companion(relative_path, source)
            actual_identity = {
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if actual_identity != EXPECTED_ARTIFACT_IDENTITIES[relative_path]:
                companion_failures.append(
                    relative_path + ":static_contract_identity_mismatch")
            observed_companions.append({
                "path": relative_path,
                **actual_identity,
                "validated_pass": not companion_failures,
                "failures": sorted(set(companion_failures)),
            })
            failures.extend(companion_failures)
        except (OSError, UnicodeError) as error:
            failures.append(
                relative_path + ":read_failed:" + type(error).__name__)
    domains = [ACTIVE_LEGACY[path]["domain"] for path in ACTIVE_LEGACY]
    if len(set(domains)) != len(domains) or 137 in domains:
        failures.append("legacy_offline_domains_not_unique_or_use_137")
    failures = sorted(set(failures))
    return {
        "gate_id": "LEGACY_ROS2_OPERATIONAL_SCRIPT_POLICY_V1",
        "field_runtime_authority": "ROS1_NOETIC",
        "read_only": True,
        "authorizes_ros_start": False,
        "authorizes_hardware_access": False,
        "authorizes_motion": False,
        "authorizes_goal": False,
        "authorizes_nonzero_twist": False,
        "authorizes_recovery": False,
        "release_pin_may_be_updated": False,
        "legacy_script_count": len(LEGACY_PATHS),
        "bridge_exception_count": len(BRIDGE_ALLOWLIST),
        "companion_static_contract_count": len(COMPANION_PATHS),
        "source_tree_contract_only": True,
        "installed_runtime_resolution_verified": False,
        "runtime_execution_ready": False,
        "observed_scripts": observed,
        "observed_companions": observed_companions,
        "failures": failures,
        "validated_pass": not failures,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        print("usage: legacy_ros2_operational_script_policy.py", file=sys.stderr)
        return 64
    result = validate_workspace()
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["validated_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
