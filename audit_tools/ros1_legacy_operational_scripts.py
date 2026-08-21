"""Fail-closed gate for retired visual ROS 2 operational scripts.

The four scripts enumerated here are historical/offline helpers.  This module
only reads and parses their bytes; it never invokes a shell, ROS, a model, a
camera, a device, or an executor.  A script is admitted only when its legacy
opt-in guard precedes every executable ROS surface and its reachable body has
the exact permanent-shim or isolated-mock role assigned below.

Explicit ROS1<->ROS2 bridge tools are deliberately outside this visual gate.
They have their own base/bridge authority and are not discovered by filename,
directory scan, or mtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "ros1_legacy_operational_scripts/v1"
MARKER = "ROS1_LEGACY_OPERATIONAL_SCRIPTS "
OPT_IN_VARIABLE = "LIMO_ALLOW_LEGACY_ROS2_OFFLINE"
GUARD_LINE = 'if [[ "${LIMO_ALLOW_LEGACY_ROS2_OFFLINE:-}" != \'1\' ]]; then'

SCRIPT_PATHS: Tuple[str, ...] = (
    "scripts/smoke_test_real_perception_startup.sh",
    "scripts/smoke_test_perception.sh",
    "scripts/audit_foxy_runtime.sh",
    "scripts/smoke_test_mock_system.sh",
)

# These are named explicitly so a future directory-wide caller cannot quietly
# absorb bridge scripts into this visual policy.
EXCLUDED_ROS1_ROS2_BRIDGE_ALLOWLIST: Tuple[str, ...] = (
    "scripts/ros1_base_bridge_preflight.sh",
    "scripts/run_ros1_base_bridge_zero_stage.sh",
)

PERMANENT_SHIMS = frozenset((
    "scripts/smoke_test_real_perception_startup.sh",
    "scripts/audit_foxy_runtime.sh",
))
MOCK_SCRIPTS = frozenset((
    "scripts/smoke_test_perception.sh",
    "scripts/smoke_test_mock_system.sh",
))

EXPECTED_DOMAIN_BY_SCRIPT: Mapping[str, str] = {
    "scripts/smoke_test_perception.sh": "193",
    "scripts/smoke_test_mock_system.sh": "194",
}

EXPECTED_BANNER_BY_SCRIPT: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_real_perception_startup.sh": (
        "# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY",
        "# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN",
        "# NOT_FIELD_OR_DELIVERY_EVIDENCE",
    ),
    "scripts/smoke_test_perception.sh": (
        "# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY",
        "# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN",
        "# NOT_FIELD_OR_DELIVERY_EVIDENCE",
    ),
    "scripts/audit_foxy_runtime.sh": (
        "# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY",
        "# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN",
        "# NOT_NOETIC_BUILD_INSTALL_FIELD_OR_DELIVERY_EVIDENCE",
    ),
    "scripts/smoke_test_mock_system.sh": (
        "# ROS1_NOETIC_CURRENT_FIELD_AUTHORITY",
        "# LEGACY_ROS2_OFFLINE_ONLY / NON_AUTHORITATIVE_DO_NOT_RUN",
        "# NOT_NOETIC_BUILD_INSTALL_FIELD_OR_DELIVERY_EVIDENCE",
    ),
}

EXPECTED_PREGUARD_COMMANDS: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_real_perception_startup.sh": (
        "set -euo pipefail",
        "readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'",
        "readonly atomic_launcher='audit_tools/ros1_camera_only_atomic_launcher.py'",
    ),
    "scripts/smoke_test_perception.sh": (
        "set -euo pipefail",
        "readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'",
        "readonly isolated_domain='193'",
    ),
    "scripts/audit_foxy_runtime.sh": (
        "set -euo pipefail",
        "readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'",
    ),
    "scripts/smoke_test_mock_system.sh": (
        "set -euo pipefail",
        "readonly operations_index='docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md'",
        "readonly isolated_domain='194'",
    ),
}

EXPECTED_GUARD_BLOCK: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_real_perception_startup.sh": (
        GUARD_LINE,
        "echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2",
        'echo "Read ${operations_index}; production camera entry is ${atomic_launcher}." >&2',
        "exit 64",
        "fi",
    ),
    "scripts/smoke_test_perception.sh": (
        GUARD_LINE,
        "echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2",
        'echo "Read ${operations_index}." >&2',
        "exit 64",
        "fi",
    ),
    "scripts/audit_foxy_runtime.sh": (
        GUARD_LINE,
        "echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2",
        'echo "Read ${operations_index}." >&2',
        "exit 64",
        "fi",
    ),
    "scripts/smoke_test_mock_system.sh": (
        GUARD_LINE,
        "echo 'BLOCKED_LEGACY_ROS2_OFFLINE_OPT_IN_REQUIRED' >&2",
        'echo "Read ${operations_index}." >&2',
        "exit 64",
        "fi",
    ),
}

EXPECTED_SHIM_TAIL: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_real_perception_startup.sh": (
        "echo 'BLOCKED_LEGACY_REAL_PERCEPTION_NOT_PROVABLY_PURE_OFFLINE' >&2",
        "echo 'No ROS graph, model, inference, camera, topic, device, network, or hardware action was performed.' >&2",
        'echo "Read ${operations_index}; production camera entry is ${atomic_launcher}." >&2',
        "exit 65",
    ),
    "scripts/audit_foxy_runtime.sh": (
        "echo 'BLOCKED_FOXY_RUNTIME_AUDIT_REQUIRES_SEPARATE_EXPLICIT_FIELD_OR_BRIDGE_AUTHORITY' >&2",
        "echo 'No ROS source, overlay, package, graph, topic, model, camera, device, network, or hardware query was performed.' >&2",
        'echo "Read ${operations_index}." >&2',
        "exit 65",
    ),
}

EXPECTED_MOCK_SAFETY_ARGS: Tuple[str, ...] = (
    "use_mock_perception:=true",
    "use_real_perception:=false",
    "use_mock_executor:=true",
    "use_detection_gate:=true",
    "executor_dry_run:=true",
    "allow_arm_motion:=false",
    "use_gripper_controller:=false",
    "gripper_backend:=dry_run",
    "allow_gripper_motion:=false",
    "confirmed_gripper_model:=UNRESOLVED_DO_NOT_CONNECT",
    "use_tracked_base_controller:=false",
    "allow_base_motion:=false",
)

EXPECTED_SOURCE_COMMANDS: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_perception.sh": (
        "source /home/dyh/robotics/env/ros2_wsl.sh",
        "source /home/dyh/robotics/workspaces/limo_ws/install/setup.bash",
        "source /home/dyh/robotics/workspaces/limo_cleanup_ws/install/setup.bash",
    ),
    "scripts/smoke_test_mock_system.sh": (
        "source /opt/ros/foxy/setup.bash",
        'source "${workspace}/install/setup.bash"',
    ),
}

EXPECTED_ROS2_COMMANDS: Mapping[str, Tuple[str, ...]] = {
    "scripts/smoke_test_perception.sh": (
        'setsid ros2 launch limo_cleanup_bringup cleanup_system.launch.py '
        '"${mock_safety_args[@]}" "$@" > "$launch_log" 2>&1 &',
        'setsid ros2 topic echo /cleanup/status > "$status_log" 2>&1 &',
        'ros2 topic pub --once /cleanup/command_text std_msgs/msg/String '
        '"{data: \'捡纸盒\'}" > /dev/null',
        'ros2 topic pub --once /cleanup/command_text std_msgs/msg/String '
        '"{data: \'捡塑料瓶\'}" > /dev/null',
        'ros2 topic pub --once /cleanup/command_text std_msgs/msg/String '
        '"{data: \'捡易拉罐\'}" > /dev/null',
        'ros2 topic pub --once /cleanup/command_text std_msgs/msg/String '
        '"{data: \'停止任务\'}" > /dev/null',
        'ros2 topic pub --once /cleanup/command_text std_msgs/msg/String '
        '"{data: \'捡塑料瓶\'}" > /dev/null',
    ),
    "scripts/smoke_test_mock_system.sh": (
        'setsid ros2 launch limo_cleanup_bringup cleanup_system.launch.py '
        '"${mock_safety_args[@]}" >"$log_file" 2>&1 &',
    ),
}

EXPECTED_START_SYSTEM_CALLS: Tuple[str, ...] = (
    'start_system "$normal_launch" mock_step_duration:=0.10 '
    'mock_detection_delay:=0.30 detection_timeout:=2.0',
    'start_system "$timeout_launch" mock_step_duration:=0.10 '
    'mock_detection_delay:=3.0 detection_timeout:=0.60',
    'start_system "$cancel_launch" mock_step_duration:=0.10 '
    'mock_detection_delay:=3.0 detection_timeout:=5.0',
    'start_system "$gate_launch" mock_step_duration:=0.10 '
    'mock_detection_delay:=0.30 mock_detection_confidence:=0.10 '
    'detection_timeout:=1.0',
)

# Host-owned ordered inventories for every executable logical command that is
# reachable from each fixed script.  This deliberately binds shell structure,
# not comments or prose: adding a new helper/function/wrapper, changing a
# command path, or moving an old ROS2 command into a newly reachable position
# cannot become admissible merely because a token blacklist did not model the
# chosen shell spelling.
EXPECTED_REACHABLE_COMMAND_INVENTORY: Mapping[str, Mapping[str, Any]] = {
    "scripts/smoke_test_real_perception_startup.sh": {
        "count": 12,
        "sha256": (
            "2a9e18fea881d31406e188fa81f54ff8284784e6d2a347a59279c6160815fdac"),
    },
    "scripts/smoke_test_perception.sh": {
        "count": 128,
        "sha256": (
            "54cee29f1bcdd92634635c927b0164b9a8ef41f1f1ab66144c733c851c4e20ec"),
    },
    "scripts/audit_foxy_runtime.sh": {
        "count": 11,
        "sha256": (
            "eaf544870e4f0e9c52149cab5dc916e07942d60ac6096a967500d676571f1d66"),
    },
    "scripts/smoke_test_mock_system.sh": {
        "count": 90,
        "sha256": (
            "06d1af8f8b2599fef20232052284dcf3530ebecd6ed5de29fe933b39fdbb2fdc"),
    },
}

MOCK_SYSTEM_ARGUMENT_GUARD: Tuple[str, ...] = (
    'if [[ "$#" -ne 0 ]]; then',
    "echo 'BLOCKED_LEGACY_ROS2_UNDERLAY_OR_WORKSPACE_OVERRIDE_FORBIDDEN' >&2",
    'echo "Read ${operations_index}." >&2',
    "exit 66",
    "fi",
)

MOCK_SYSTEM_ROOT_COMMANDS: Tuple[str, ...] = (
    'script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"',
    'workspace="$(cd -- "${script_dir}/.." && pwd -P)"',
)

FORBIDDEN_REACHABLE_CONFIGURATION: Tuple[str, ...] = (
    "start_camera:=true",
    "use_real_perception:=true",
    "use_mock_perception:=false",
    "use_mock_executor:=false",
    "executor_dry_run:=false",
    "allow_arm_motion:=true",
    "use_gripper_controller:=true",
    "allow_gripper_motion:=true",
    "use_tracked_base_controller:=true",
    "allow_base_motion:=true",
)

DISALLOWED_REACHABLE_EXECUTABLES = frozenset((
    "alias", "awk", "bash", "builtin", "dash", "eval", "exec", "env",
    "command", "gawk", "ksh", "mawk", "nice", "node", "nodejs",
    "nohup", "perl", "perl5", "python", "python2", "python3", "ruby",
    "sh", "shopt", "stdbuf", "time", "timeout", "zsh", "colcon",
    "roslaunch",
    "curl", "wget", "ssh", "scp", "nc", "ncat", "socat",
    "v4l2-ctl", "lsusb", "udevadm", "ffmpeg", "gst-launch-1.0",
))
_DYNAMIC_COMMAND_POSITION = re.compile(
    r"(?:^|[;&|]\s*)(?:if\s+|while\s+|until\s+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=[^\s]+\s+)*"
    r"(?:setsid\s+)?(?:[\"']?\$|`)")
_RISKY_COMMAND_SUBSTITUTION = re.compile(
    r"\$\([^\r\n)]*\b(?:ros2|roslaunch|colcon|python[0-9.]*|curl|wget|"
    r"ssh|v4l2-ctl|ffmpeg)\b")
_REAL_DEVICE_SURFACE = re.compile(
    r"(?<![A-Za-z0-9_])/dev/(?!null(?:[^A-Za-z0-9_]|$))")

INVALID_OPT_IN_CASES: Tuple[Tuple[str, Optional[str]], ...] = (
    ("unset", None),
    ("empty", ""),
    ("zero", "0"),
    ("true", "true"),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_linklike(metadata: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse)


def _identity_tuple(metadata: os.stat_result) -> Tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(getattr(metadata, "st_nlink", 1)),
        int(metadata.st_size),
        int(getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1e9))),
    )


def _read_regular_artifact(
        root: Path, relative_path: str) -> Tuple[Optional[bytes], List[str]]:
    """Reopen one fixed path and reject links, hardlinks, or identity drift."""
    failures: List[str] = []
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None, ["legacy_script_path_invalid:" + relative_path]
    candidate = root.joinpath(*relative.parts)
    parent = root
    for component in relative.parts[:-1]:
        parent = parent / component
        try:
            parent_info = os.lstat(str(parent))
        except OSError:
            return None, ["legacy_script_parent_unavailable:" + relative_path]
        if _is_linklike(parent_info):
            return None, ["legacy_script_parent_linklike:" + relative_path]
        if not stat.S_ISDIR(parent_info.st_mode):
            return None, ["legacy_script_parent_not_directory:" + relative_path]
    try:
        before = os.lstat(str(candidate))
    except OSError:
        return None, ["legacy_script_unavailable:" + relative_path]
    if _is_linklike(before):
        return None, ["legacy_script_artifact_linklike:" + relative_path]
    if not stat.S_ISREG(before.st_mode):
        return None, ["legacy_script_artifact_not_regular:" + relative_path]
    if int(getattr(before, "st_nlink", 1)) != 1:
        return None, ["legacy_script_artifact_hardlink:" + relative_path]

    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = -1
    try:
        descriptor = os.open(str(candidate), flags)
        opened = os.fstat(descriptor)
        chunks: List[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    except OSError:
        return None, ["legacy_script_open_failed:" + relative_path]
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        after = os.lstat(str(candidate))
    except OSError:
        return None, ["legacy_script_final_reopen_failed:" + relative_path]
    if (_is_linklike(opened) or not stat.S_ISREG(opened.st_mode)
            or int(getattr(opened, "st_nlink", 1)) != 1
            or _identity_tuple(before) != _identity_tuple(opened)
            or _identity_tuple(before) != _identity_tuple(after)
            or len(raw) != int(opened.st_size)):
        failures.append("legacy_script_identity_drift:" + relative_path)
        return None, failures
    return raw, failures


def _executable_lines(text: str) -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []
    for number, physical in enumerate(text.splitlines(), 1):
        value = physical.strip()
        if not value or value.startswith("#"):
            continue
        result.append((number, value))
    return result


def _logical_commands(text: str) -> List[Tuple[int, str]]:
    commands: List[Tuple[int, str]] = []
    pending: List[str] = []
    start = 0
    for number, physical in enumerate(text.splitlines(), 1):
        value = physical.strip()
        if not value or value.startswith("#"):
            continue
        continued = value.endswith("\\")
        fragment = value[:-1].rstrip() if continued else value
        if pending:
            pending.append(fragment)
        elif continued:
            start = number
            pending = [fragment]
        else:
            commands.append((number, fragment))
        if pending and not continued:
            commands.append((start, " ".join(pending)))
            pending = []
            start = 0
    if pending:
        commands.append((start, " ".join(pending)))
    return commands


def _tokens(command: str) -> Optional[List[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.commenters = ""
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _token_basename(token: str) -> str:
    return token.rstrip("\\/").rsplit("/", 1)[-1].lower()


def _contains_executable_basename(command: str, basename: str) -> bool:
    parsed = _tokens(command)
    if parsed is None:
        return False
    expected = basename.lower()
    return any(_token_basename(token) == expected for token in parsed)


def _reachable_command_inventory(
        commands: Sequence[Tuple[int, str]]) -> Dict[str, Any]:
    ordered = tuple(command for _, command in commands)
    raw = ("\n".join(ordered) + "\n").encode("utf-8")
    return {
        "count": len(ordered),
        "sha256": _sha256(raw),
    }


def _block_at(lines: Sequence[str], start: int, expected: Sequence[str]) -> bool:
    return tuple(value.strip() for value in lines[start:start + len(expected)]) == tuple(expected)


def _extract_mock_safety_args(text: str) -> Optional[Tuple[str, ...]]:
    lines = text.splitlines()
    starts = [index for index, value in enumerate(lines)
              if value.strip() == "readonly -a mock_safety_args=("]
    if len(starts) != 1:
        return None
    values: List[str] = []
    for value in lines[starts[0] + 1:]:
        stripped = value.strip()
        if stripped == ")":
            return tuple(values)
        if not stripped or stripped.startswith("#"):
            continue
        values.append(stripped)
    return None


def _source_commands(commands: Iterable[Tuple[int, str]]) -> Tuple[str, ...]:
    return tuple(command for _, command in commands
                 if command == "source" or command.startswith("source ")
                 or command == "." or command.startswith(". "))


def _ros2_role_allowed(relative_path: str, command: str) -> bool:
    parsed = _tokens(command)
    if parsed is None:
        return False
    ros2_indices = [
        index for index, token in enumerate(parsed)
        if _token_basename(token) == "ros2"]
    if not ros2_indices:
        return True
    if len(ros2_indices) != 1:
        return False
    index = ros2_indices[0]
    role = list(parsed[index:])
    role[0] = "ros2"
    if len(role) >= 4 and role[:4] == [
            "ros2", "launch", "limo_cleanup_bringup",
            "cleanup_system.launch.py"]:
        return "${mock_safety_args[@]}" in role
    if relative_path != "scripts/smoke_test_perception.sh":
        return False
    if len(role) >= 4 and role[:4] == [
            "ros2", "topic", "echo", "/cleanup/status"]:
        return True
    if len(role) >= 6 and role[:3] == ["ros2", "topic", "pub"]:
        return ("--once" in role
                and "/cleanup/command_text" in role
                and "std_msgs/msg/String" in role)
    return False


def _disallowed_command_surface(command: str) -> bool:
    if _DYNAMIC_COMMAND_POSITION.search(command):
        return True
    if _RISKY_COMMAND_SUBSTITUTION.search(command):
        return True
    if _REAL_DEVICE_SURFACE.search(command):
        return True
    parsed = _tokens(command)
    if parsed is None:
        return False
    for token in parsed:
        normalized = token.rsplit("/", 1)[-1]
        if normalized in DISALLOWED_REACHABLE_EXECUTABLES:
            return True
    return False


def _reachable_commands(
        relative_path: str, text: str) -> Tuple[List[Tuple[int, str]], int]:
    commands = _logical_commands(text)
    if relative_path not in PERMANENT_SHIMS:
        return commands, 0
    for index, (_, command) in enumerate(commands):
        if command == "exit 65":
            return commands[:index + 1], index + 1
    return commands, -1


def _guard_case_report(
        relative_path: str, text: str,
        value: Optional[str]) -> Dict[str, Any]:
    lines = text.splitlines()
    positions = [index for index, line in enumerate(lines)
                 if line.strip() == GUARD_LINE]
    exact = (len(positions) == 1
             and _block_at(lines, positions[0],
                           EXPECTED_GUARD_BLOCK[relative_path]))
    if not exact:
        return {
            "guard_validated": False,
            "environment_value": value,
            "would_execute_ros": False,
            "would_call_exec": False,
            "exit_code": None,
        }
    if value != "1":
        exit_code: Optional[int] = 64
    elif relative_path in PERMANENT_SHIMS:
        exit_code = 65
    else:
        exit_code = None
    return {
        "guard_validated": True,
        "environment_value": value,
        "would_execute_ros": False,
        "would_call_exec": False,
        "exit_code": exit_code,
    }


def scan_script_text(relative_path: str, text: str) -> Dict[str, Any]:
    """Validate one assigned script without executing any of its contents."""
    failures: List[str] = []
    if relative_path not in SCRIPT_PATHS:
        return {
            "failures": ["legacy_script_not_in_fixed_inventory:" + relative_path],
            "guard_cases": [],
            "mode": "UNASSIGNED",
        }
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#!/usr/bin/env bash":
        failures.append("legacy_script_shebang_invalid:" + relative_path)

    banner_window = tuple(line.strip() for line in lines[:20])
    for banner in EXPECTED_BANNER_BY_SCRIPT[relative_path]:
        if banner_window.count(banner) != 1:
            failures.append("legacy_script_banner_invalid:" + relative_path)

    guard_positions = [index for index, line in enumerate(lines)
                       if line.strip() == GUARD_LINE]
    if len(guard_positions) != 1:
        failures.append("legacy_script_guard_count_invalid:" + relative_path)
        guard_index = -1
        guard_end = -1
    else:
        guard_index = guard_positions[0]
        expected_guard = EXPECTED_GUARD_BLOCK[relative_path]
        if not _block_at(lines, guard_index, expected_guard):
            failures.append("legacy_script_guard_block_invalid:" + relative_path)
            guard_end = -1
        else:
            guard_end = guard_index + len(expected_guard)
        preguard = tuple(value for _, value in _executable_lines(
            "\n".join(lines[:guard_index])))
        if preguard != EXPECTED_PREGUARD_COMMANDS[relative_path]:
            failures.append("legacy_script_preguard_inventory_invalid:" + relative_path)

    if relative_path in PERMANENT_SHIMS:
        expected_tail = EXPECTED_SHIM_TAIL[relative_path]
        tail_executable = tuple(
            value for _, value in _executable_lines(
                "\n".join(lines[guard_end:]))) if guard_end >= 0 else ()
        if tail_executable[:len(expected_tail)] != expected_tail:
            failures.append("legacy_script_permanent_shim_tail_invalid:" + relative_path)
        reachable, terminal_index = _reachable_commands(relative_path, text)
        if terminal_index < 0:
            failures.append("legacy_script_permanent_shim_exit_missing:" + relative_path)
        elif not reachable or reachable[-1][1] != "exit 65":
            failures.append("legacy_script_permanent_shim_not_terminal:" + relative_path)
    else:
        reachable, _ = _reachable_commands(relative_path, text)

    inventory = _reachable_command_inventory(reachable)
    if inventory != EXPECTED_REACHABLE_COMMAND_INVENTORY[relative_path]:
        failures.append(
            "legacy_script_reachable_command_inventory_invalid:" +
            relative_path)

    reachable_text = "\n".join(command for _, command in reachable)
    for token in FORBIDDEN_REACHABLE_CONFIGURATION:
        if token in reachable_text:
            failures.append(
                "legacy_script_unsafe_configuration:{}:{}".format(
                    relative_path, token))

    if relative_path in MOCK_SCRIPTS:
        domain = EXPECTED_DOMAIN_BY_SCRIPT[relative_path]
        environment_sequence = (
            "export ROS_LOCALHOST_ONLY=1",
            'export ROS_DOMAIN_ID="${isolated_domain}"',
            "unset ROS_DISCOVERY_SERVER CYCLONEDDS_URI FASTRTPS_DEFAULT_PROFILES_FILE",
        )
        reachable_values = tuple(command for _, command in reachable)
        try:
            environment_index = reachable_values.index(environment_sequence[0])
        except ValueError:
            environment_index = -1
        if (environment_index < 0
                or reachable_values[
                    environment_index:environment_index + 3] != environment_sequence):
            failures.append("legacy_script_isolation_environment_invalid:" + relative_path)
        if "readonly isolated_domain='{}'".format(domain) not in text:
            failures.append("legacy_script_domain_invalid:" + relative_path)
        if any(token in reachable_text for token in (
                "${ROS_SETUP", "$ROS_SETUP", "ROS_SETUP=",
                "${UNDERLAY", "$UNDERLAY", "UNDERLAY=",
                "${ROS_PACKAGE_PATH", "$ROS_PACKAGE_PATH", "ROS_PACKAGE_PATH=",
                "${PYTHONPATH", "$PYTHONPATH", "PYTHONPATH=",
                "${PYTHONHOME", "$PYTHONHOME", "PYTHONHOME=",
                "${LD_LIBRARY_PATH", "$LD_LIBRARY_PATH", "LD_LIBRARY_PATH=",
                "${LD_PRELOAD", "$LD_PRELOAD", "LD_PRELOAD=")):
            failures.append("legacy_script_ambient_runtime_input:" + relative_path)

        safety_args = _extract_mock_safety_args(text)
        if safety_args != EXPECTED_MOCK_SAFETY_ARGS:
            failures.append("legacy_script_mock_safety_args_invalid:" + relative_path)

        sources = _source_commands(reachable)
        if sources != EXPECTED_SOURCE_COMMANDS[relative_path]:
            failures.append("legacy_script_source_inventory_invalid:" + relative_path)
        source_line_numbers = [number for number, command in reachable
                               if command == "source"
                               or command.startswith("source ")
                               or command == "." or command.startswith(". ")]
        ros2_line_numbers = [number for number, command in reachable
                             if _contains_executable_basename(command, "ros2")]
        environment_line = next(
            (number for number, command in reachable
             if command == environment_sequence[0]), -1)
        if (environment_line < 0
                or any(number >= environment_line
                       for number in source_line_numbers)
                or any(number <= environment_line
                       for number in ros2_line_numbers)):
            failures.append("legacy_script_isolation_order_invalid:" + relative_path)

        isolation_commands = tuple(
            command for _, command in reachable
            if any(name in command for name in (
                "ROS_LOCALHOST_ONLY", "ROS_DOMAIN_ID",
                "ROS_DISCOVERY_SERVER", "CYCLONEDDS_URI",
                "FASTRTPS_DEFAULT_PROFILES_FILE"))
        )
        if isolation_commands != environment_sequence:
            failures.append(
                "legacy_script_isolation_environment_inventory_invalid:" +
                relative_path)
        safety_line = next(
            (number for number, command in reachable
             if command == "readonly -a mock_safety_args=("), -1)
        launch_lines = [number for number, command in reachable
                        if "ros2 launch" in command]
        if (safety_line < 0
                or any(number <= safety_line for number in launch_lines)):
            failures.append("legacy_script_mock_safety_order_invalid:" + relative_path)
        if relative_path == "scripts/smoke_test_mock_system.sh":
            reachable_values = tuple(command for _, command in reachable)
            argument_guard_positions = [
                index for index, command in enumerate(reachable_values)
                if command == MOCK_SYSTEM_ARGUMENT_GUARD[0]]
            argument_guard_valid = (
                len(argument_guard_positions) == 1
                and reachable_values[
                    argument_guard_positions[0]:
                    argument_guard_positions[0] + len(MOCK_SYSTEM_ARGUMENT_GUARD)
                ] == MOCK_SYSTEM_ARGUMENT_GUARD)
            if not argument_guard_valid:
                failures.append(
                    "legacy_script_workspace_argument_guard_invalid:" +
                    relative_path)
            root_positions = [
                index for index, command in enumerate(reachable_values)
                if command == MOCK_SYSTEM_ROOT_COMMANDS[0]]
            root_valid = (
                len(root_positions) == 1
                and reachable_values[
                    root_positions[0]:root_positions[0] + 2
                ] == MOCK_SYSTEM_ROOT_COMMANDS)
            if (not root_valid
                    or any(token in reachable_text
                           for token in ("${1", "$1", "$@", "$*"))):
                failures.append("legacy_script_workspace_root_invalid:" + relative_path)

        actual_ros2_commands = tuple(
            command for _, command in reachable
            if _contains_executable_basename(command, "ros2")
        )
        if actual_ros2_commands != EXPECTED_ROS2_COMMANDS[relative_path]:
            failures.append(
                "legacy_script_ros2_command_inventory_invalid:" +
                relative_path)

        actual_start_system_calls = tuple(
            command for _, command in reachable
            if command.startswith("start_system ")
        )
        expected_start_system_calls = (
            EXPECTED_START_SYSTEM_CALLS
            if relative_path == "scripts/smoke_test_perception.sh" else ()
        )
        if actual_start_system_calls != expected_start_system_calls:
            failures.append(
                "legacy_script_mock_scenario_inventory_invalid:" +
                relative_path)

        safety_references = tuple(
            command for _, command in reachable
            if "mock_safety_args" in command
        )
        expected_safety_references = (
            "readonly -a mock_safety_args=(",
            EXPECTED_ROS2_COMMANDS[relative_path][0],
        )
        if safety_references != expected_safety_references:
            failures.append(
                "legacy_script_mock_safety_reference_invalid:" +
                relative_path)

        for number, command in reachable:
            parsed = _tokens(command)
            if parsed is None:
                failures.append(
                    "legacy_script_shell_parse_failed:{}:{}".format(
                        relative_path, number))
                continue
            if _disallowed_command_surface(command):
                failures.append(
                    "legacy_script_disallowed_command_surface:{}:{}".format(
                        relative_path, number))
            if "roslaunch" in parsed:
                failures.append(
                    "legacy_script_roslaunch_not_allowed:{}:{}".format(
                        relative_path, number))
            if (_contains_executable_basename(command, "ros2")
                    and not _ros2_role_allowed(
                        relative_path, command)):
                failures.append(
                    "legacy_script_ros2_role_not_allowlisted:{}:{}".format(
                        relative_path, number))

    guard_cases = []
    for label, value in INVALID_OPT_IN_CASES:
        case = _guard_case_report(relative_path, text, value)
        case["case"] = label
        guard_cases.append(case)
    if relative_path in PERMANENT_SHIMS:
        case = _guard_case_report(relative_path, text, "1")
        case["case"] = "exact_opt_in"
        guard_cases.append(case)

    return {
        "failures": sorted(set(failures)),
        "guard_cases": guard_cases,
        "mode": ("PERMANENT_FAIL_CLOSED_SHIM"
                 if relative_path in PERMANENT_SHIMS
                 else "ISOLATED_LEGACY_MOCK_ONLY"),
        "runtime_execution_performed": False,
        "ros_commands_executed": 0,
        "exec_calls": 0,
    }


def evaluate_legacy_scripts(workspace_root: Path) -> Dict[str, Any]:
    """Read the fixed script inventory and return a release-safe report."""
    root = workspace_root.resolve(strict=True)
    failures: List[str] = []
    artifacts: List[Dict[str, Any]] = []
    guard_results: List[Dict[str, Any]] = []
    if len(SCRIPT_PATHS) != len(set(SCRIPT_PATHS)):
        failures.append("legacy_script_fixed_inventory_duplicate")
    if set(SCRIPT_PATHS) & set(EXCLUDED_ROS1_ROS2_BRIDGE_ALLOWLIST):
        failures.append("legacy_script_bridge_allowlist_overlap")

    for relative_path in SCRIPT_PATHS:
        raw, identity_failures = _read_regular_artifact(root, relative_path)
        failures.extend(identity_failures)
        if raw is None:
            continue
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("legacy_script_utf8_invalid:" + relative_path)
            continue
        semantic = scan_script_text(relative_path, text)
        failures.extend(semantic["failures"])
        for case in semantic["guard_cases"]:
            bound_case = dict(case)
            bound_case["path"] = relative_path
            guard_results.append(bound_case)
        artifacts.append({
            "role": "legacy_operational_script",
            "path": relative_path,
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
            "mode": semantic["mode"],
            "ordinary_non_link_file": True,
            "runtime_execution_performed": False,
        })

    unique_failures = sorted(set(failures))
    invalid_cases = [case for case in guard_results
                     if case["case"] != "exact_opt_in"]
    invalid_cases_validated = (
        len(invalid_cases) == len(SCRIPT_PATHS) * len(INVALID_OPT_IN_CASES)
        and all(case["guard_validated"]
                and case["exit_code"] == 64
                and not case["would_execute_ros"]
                and not case["would_call_exec"]
                for case in invalid_cases))
    shim_cases = [case for case in guard_results
                  if case["case"] == "exact_opt_in"]
    shims_validated = (
        len(shim_cases) == len(PERMANENT_SHIMS)
        and all(case["guard_validated"]
                and case["exit_code"] == 65
                and not case["would_execute_ros"]
                and not case["would_call_exec"]
                for case in shim_cases))
    if not invalid_cases_validated:
        unique_failures = sorted(set(unique_failures + [
            "legacy_script_invalid_opt_in_matrix_not_validated"]))
    if not shims_validated:
        unique_failures = sorted(set(unique_failures + [
            "legacy_script_permanent_shim_matrix_not_validated"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "validated_pass": not unique_failures,
        "failures": unique_failures,
        "scripts_expected": list(SCRIPT_PATHS),
        "bridge_allowlist_explicitly_excluded": list(
            EXCLUDED_ROS1_ROS2_BRIDGE_ALLOWLIST),
        "artifacts": artifacts,
        "guard_case_results": guard_results,
        "invalid_opt_in_exit64_validated": invalid_cases_validated,
        "permanent_shim_opt_in_blocked": shims_validated,
        "runtime_execution_performed": False,
        "ros_commands_executed": 0,
        "exec_calls": 0,
        "ros1_noetic_runtime_install_validated": False,
        "formal_denominator": 0,
        "formal_consumer": False,
        "authorizes_field_delivery": False,
        "delivery_ready": False,
    }


def _cli_failure(code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "validated_pass": False,
        "failures": [code],
        "scripts_expected": list(SCRIPT_PATHS),
        "runtime_execution_performed": False,
        "ros_commands_executed": 0,
        "exec_calls": 0,
        "ros1_noetic_runtime_install_validated": False,
        "formal_denominator": 0,
        "formal_consumer": False,
        "authorizes_field_delivery": False,
        "delivery_ready": False,
    }


def main(args: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if args is None else args)
    if arguments:
        report = _cli_failure("legacy_script_unexpected_cli_arguments")
        exit_code = 64
    else:
        try:
            workspace = Path(__file__).resolve().parents[1]
            report = evaluate_legacy_scripts(workspace)
        except Exception as exc:  # pragma: no cover - exercised through mock
            report = _cli_failure(
                "legacy_script_internal_error:" + type(exc).__name__)
        exit_code = 0 if report["validated_pass"] else 4
    sys.stdout.write(MARKER + json.dumps(
        report, sort_keys=True, separators=(",", ":")) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
