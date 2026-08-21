"""Fail-closed static gate for camera-only operator documentation.

This tool never runs shell text.  It enumerates the authoritative operational
documents, extracts fenced or indented shell blocks, and rejects legacy DaBai
camera entry points unless they are explicitly marked as historical.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import stat
import sys
from typing import Any, Dict, Iterable, List, Sequence, Tuple


SCHEMA_VERSION = "ros1_camera_only_operator_docs/v1"
MARKER = "ROS1_CAMERA_ONLY_OPERATOR_DOCS "
HISTORICAL_PREFIX = "# HISTORICAL/NON_AUTHORITATIVE/DO NOT RUN:"
LEGACY_NONAUTHORITATIVE_PREFIX = (
    "# LEGACY_NONAUTHORITATIVE/DO NOT RUN:")
OPERATIONAL_DOCUMENTS: Tuple[str, ...] = (
    "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md",
    "docs/hardware_readiness.md",
    "docs/real_perception.md",
    "docs/limo_pro_manual_reference.md",
    "docs/REAL_CAMERA_READONLY_ACCEPTANCE_TEMPLATE.md",
)
RETIRED_SCRIPT = "scripts/start_dabai_camera.sh"
AUTHORITY_RUNBOOK = OPERATIONAL_DOCUMENTS[0]
LEGACY_CAMERA_TEMPLATE = OPERATIONAL_DOCUMENTS[-1]
HARDWARE_READINESS_DOCUMENT = "docs/hardware_readiness.md"
HARDWARE_READINESS_REDIRECT = (
    "docs/HARDWARE_READINESS_ROS1_NOETIC_REDIRECT.md")
HARDWARE_READINESS_IDENTITY = {
    "size_bytes": 13274,
    "sha256": "6d48815b660c3f6b0c00fb36dc633d403b540e5a95f0bdedaddc37f33093fd9b",
}
HARDWARE_REDIRECT_IDENTITY = {
    "size_bytes": 1592,
    "sha256": "7cca88b27c8add2f91cc3133b06d7f0f8dba9812b10558fe8def795d2415f4a0",
}
LEGACY_CAMERA_TEMPLATE_HEADER: Tuple[str, ...] = (
    "# HISTORICAL ROS2/Foxy camera worksheet — NON_AUTHORITATIVE / DO NOT RUN",
    "",
    "> [!CAUTION]",
    "> **ROS1/Noetic is the current field authority. / "
    "当前现场权威为 ROS1 Noetic。**",
    "> This file is retained only as historical ROS2/Foxy/rosbag2 provenance. It",
    "> must not be run and cannot prove or authorize current ROS1/Noetic build,",
    "> install, camera operation, four-scene evidence, TF/3D, latency, field, or",
    "> delivery PASS. / 本文仅保留历史迁移事实，禁止执行，也不能授权当前现场或交付。",
    "> Start from",
    "> [`docs/PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md`]"
    "(PERCEPTION_V2_CURRENT_OPERATIONS_INDEX.md),",
    "> then follow the ROS1/Noetic field runbook to its host-owned atomic launcher.",
)
AUTHORITY_HISTORICAL_LINES: Tuple[str, ...] = (
    HISTORICAL_PREFIX + " source /opt/ros/noetic/setup.bash",
    HISTORICAL_PREFIX + " source ~/agilex_ws/devel/setup.bash",
    HISTORICAL_PREFIX + " roslaunch astra_camera dabai_u3.launch",
)
EXPECTED_HISTORICAL_COMMANDS_BY_DOCUMENT = {
    AUTHORITY_RUNBOOK: AUTHORITY_HISTORICAL_LINES,
    "docs/hardware_readiness.md": (
        HISTORICAL_PREFIX + " roslaunch astra_camera dabai_u3.launch",
    ),
    "docs/real_perception.md": (
        HISTORICAL_PREFIX + " roslaunch astra_camera dabai_u3.launch",
    ),
    "docs/limo_pro_manual_reference.md": (
        HISTORICAL_PREFIX + " roslaunch astra_camera dabai_u3.launch",
        HISTORICAL_PREFIX + " source ~/agilex_ws/devel/setup.bash",
        HISTORICAL_PREFIX + " roslaunch limo_bringup limo_start.launch",
        HISTORICAL_PREFIX
        + " roslaunch limo_bringup limo_teletop_keyboard.launch",
    ),
}

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_SHELL_LANGUAGES = {
    "", "bash", "console", "sh", "shell", "shell-session", "zsh",
}
_RETIRED_SCRIPT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])start_dabai_camera\.sh"
    r"(?![A-Za-z0-9_.-])")
_ROSLAUNCH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])roslaunch(?![A-Za-z0-9_.-])")
_SHELL_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_SHELL_OPERATORS = {
    "&", "&&", "(", ")", ";", ";;", "|", "||", "{", "}",
}
_COMMAND_WRAPPERS = {
    "command", "env", "exec", "nice", "nohup", "setsid", "stdbuf",
    "sudo", "time", "timeout",
}
_SHELL_CONTROL_PREFIXES = {"!", "do", "elif", "else", "if", "then", "until", "while"}
_SHELL_CONTROL_TERMINATORS = {"done", "fi"}
_SHELL_META_COMMANDS = {"alias", "shopt", "unalias"}
_NON_EXECUTING_LITERAL_COMMANDS = {"echo"}
_ROS2_SUBCOMMANDS = {
    "action", "bag", "component", "launch", "node", "param", "run",
    "service", "topic",
}
_ROS2_GLOBAL_OPTIONS_WITH_VALUES = {
    "--domain-id", "--enclave", "--log-level",
}
_WRAPPER_OPTIONS_WITH_VALUES = {
    "env": {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"},
    "exec": {"-a"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-e", "--error", "-i", "--input", "-o", "--output"},
    "sudo": {
        "-C", "--close-from", "-D", "--chdir", "-g", "--group",
        "-h", "--host", "-p", "--prompt", "-R", "--chroot",
        "-T", "--command-timeout", "-u", "--user",
    },
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
}
_WRAPPER_POSITIONAL_PREFIX_COUNTS = {"timeout": 1}
_CONSOLE_PROMPTS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:\([^\r\n)]*\)\s*)?\$\s+"),
    re.compile(
        r"^(?:\([^\r\n]*\)\s*)?[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:"
        r"[^\r\n$#]*[$#]\s+"),
    re.compile(
        r"^(?:\([^\r\n]*\)\s*)?[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+"
        r"[$#]\s+"),
    re.compile(
        r"^\[[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+"
        r"(?:\s+[^\]\r\n]*)?\][$#]\s+"),
)
FORMAL_CAPTURE_COMMAND = (
    'roslaunch limo_cleanup_ros1_perception '
    'perception_v2_formal_capture.launch '
    'task_id:="$TASK_ID" capture_id:="$CAPTURE_ID"'
)
ATOMIC_CAMERA_COMMAND = (
    'python3 -I -S -B audit_tools/ros1_camera_only_atomic_launcher.py '
    '--mode EXECUTE_AUDITED_CAMERA_ONLY '
    '--actual-vendor-launch "$ACTUAL_VENDOR_LAUNCH"'
)
ATOMIC_CAMERA_EXEC_PREFIX: Tuple[str, ...] = (
    "python3", "-I", "-S", "-B",
    "audit_tools/ros1_camera_only_atomic_launcher.py",
)
ATOMIC_CAMERA_REQUIRED_OPTIONS: Tuple[str, ...] = (
    "--mode", "--actual-vendor-launch",
)
ATOMIC_CAMERA_OPTION_VALUES = {
    "--mode": "EXECUTE_AUDITED_CAMERA_ONLY",
    "--actual-vendor-launch": "$ACTUAL_VENDOR_LAUNCH",
}
_FORMAL_CAPTURE_ROLE = re.compile(re.escape(FORMAL_CAPTURE_COMMAND))
_ATOMIC_CAMERA_ROLE = re.compile(re.escape(ATOMIC_CAMERA_COMMAND))
_LEGACY_TEMPLATE_SHELL_FENCE = re.compile(
    r"(?mi)^\s*(?:`{3,}|~{3,})\s*"
    r"(?:bash|console|sh|shell|shell-session|zsh)(?:\s|$)")
_LEGACY_TEMPLATE_PROMOTION = re.compile(
    r"(?i)\b(?:historical|ros2|rosbag2)\b[^\r\n]{0,160}"
    r"\b(?:is|counts\s+as|authorizes)\b[^\r\n]{0,80}"
    r"\b(?:field(?:\s+and\s+delivery)?|delivery(?:\s+and\s+field)?)"
    r"\s+PASS\b")
RETIRED_SCRIPT_SHEBANG = "#!/usr/bin/env bash"
RETIRED_SCRIPT_ALLOWED_COMMANDS: Tuple[str, ...] = (
    "set -euo pipefail",
    "echo 'ERROR: scripts/start_dabai_camera.sh is retired and never "
    "starts ROS.' >&2",
    "echo 'Use docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md and the "
    "host-owned' >&2",
    "echo 'audit_tools/ros1_camera_only_atomic_launcher.py sealed-memfd "
    "path.' >&2",
    "echo 'The atomic launcher requires --mode EXECUTE_AUDITED_CAMERA_ONLY "
    "and an' >&2",
    "echo 'explicit --actual-vendor-launch absolute path; it accepts no "
    "overrides.' >&2",
    "exit 64",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalized_command(command: str) -> str:
    return " ".join(command.strip().split())


def _strip_legacy_marker(command: str) -> Tuple[str, bool]:
    value = command.strip()
    for prefix in (HISTORICAL_PREFIX, LEGACY_NONAUTHORITATIVE_PREFIX):
        if value.startswith(prefix):
            return value[len(prefix):].strip(), True
    return value, False


def _legacy_role_record(
        relative_path: str,
        line: int,
        command: str,
        classification: Dict[str, Any],
        document_demoted: bool,
        source_kind: str,
        ) -> Dict[str, Any]:
    _, marked = _strip_legacy_marker(command)
    return {
        "role": (
            "LEGACY_NONAUTHORITATIVE"
            if document_demoted or marked
            else "UNAPPROVED_OPERATIONAL_COMMAND"),
        "path": relative_path,
        "line": line,
        "raw": command,
        "normalized": classification["normalized"],
        "actual_command": classification["actual_command"],
        "surfaces": list(classification["surfaces"]),
        "wrapper_chain": list(classification["wrapper_chain"]),
        "source_kind": source_kind,
        "exact_line_marker": marked,
        "document_level_demotion": bool(document_demoted),
    }


def _copyable_lines(text: str) -> Iterable[Tuple[int, str, bool]]:
    in_fence = False
    fence_token = ""
    fence_length = 0
    shell_fence = False
    for number, original_line in enumerate(text.splitlines(), 1):
        line = original_line
        while True:
            blockquote = re.match(r"^\s*>\s?", line)
            if blockquote is None:
                break
            line = line[blockquote.end():]
        match = _FENCE.match(line)
        if match:
            token, info = match.groups()
            if not in_fence:
                in_fence = True
                fence_token = token[0]
                fence_length = len(token)
                info = info.strip()
                language = info.split(None, 1)[0].lower() if info else ""
                if language.startswith("{."):
                    language = language[2:].rstrip("}")
                shell_fence = language in _SHELL_LANGUAGES
            elif (token[0] == fence_token and len(token) >= fence_length
                  and not info.strip()):
                in_fence = False
                fence_token = ""
                fence_length = 0
                shell_fence = False
            continue
        if in_fence:
            yield number, line.strip(), shell_fence
            continue
        if line.startswith("    ") or line.startswith("\t"):
            yield number, line.strip(), True


def _shell_lines(text: str) -> Iterable[Tuple[int, str]]:
    for number, line, is_shell in _copyable_lines(text):
        if is_shell:
            yield number, line


def _non_shell_fence_lines(text: str) -> Iterable[Tuple[int, str]]:
    for number, line, is_shell in _copyable_lines(text):
        if not is_shell:
            yield number, line


def _strip_console_prompt(line: str) -> str:
    value = line.strip()
    for pattern in _CONSOLE_PROMPTS:
        match = pattern.match(value)
        if match:
            return value[match.end():].strip()
    return value


def _logical_shell_commands(
        text: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    commands: List[Tuple[int, str]] = []
    failures: List[str] = []
    pending: List[str] = []
    pending_start = 0
    previous_number = 0
    for number, physical in _shell_lines(text):
        line = _strip_console_prompt(physical)
        if pending and number != previous_number + 1:
            failures.append(
                "operator_doc_dangling_shell_continuation:{}".format(
                    pending_start))
            pending = []
            pending_start = 0
        if not line:
            if pending:
                failures.append(
                    "operator_doc_dangling_shell_continuation:{}".format(
                        pending_start))
                pending = []
                pending_start = 0
            previous_number = number
            continue
        continued = line.endswith("\\")
        fragment = line[:-1].rstrip() if continued else line
        if pending:
            pending.append(fragment)
        elif continued:
            pending_start = number
            pending = [fragment]
        else:
            commands.append((number, fragment))
        if pending and not continued:
            commands.append((pending_start, " ".join(pending)))
            pending = []
            pending_start = 0
        previous_number = number
    if pending:
        failures.append(
            "operator_doc_dangling_shell_continuation:{}".format(
                pending_start))
    return commands, failures


def _contains_roslaunch_token(command: str) -> Tuple[bool, bool]:
    """Return (contains_roslaunch, parsed_cleanly) without executing shell."""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return False, False
    for token in tokens:
        normalized = token.strip("`$(){}")
        if normalized.rsplit("/", 1)[-1] == "roslaunch":
            return True, True
        if _ROSLAUNCH_TOKEN.search(token):
            return True, True
    return bool(_ROSLAUNCH_TOKEN.search(command)), True


def _contains_retired_script_token(command: str) -> bool:
    """Detect the retired basename after shell quote concatenation."""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return bool(_RETIRED_SCRIPT_TOKEN.search(command))
    for token in tokens:
        normalized = token.strip("`$(){}")
        if normalized.rsplit("/", 1)[-1] == "start_dabai_camera.sh":
            return True
        if _RETIRED_SCRIPT_TOKEN.search(token):
            return True
    return bool(_RETIRED_SCRIPT_TOKEN.search(command))


def _shell_tokens(command: str) -> Tuple[List[str], bool]:
    try:
        lexer = shlex.shlex(
            command, posix=True, punctuation_chars=";&|()")
        lexer.commenters = ""
        lexer.whitespace_split = True
        return list(lexer), True
    except ValueError:
        return [], False


def _token_segments(tokens: Sequence[str]) -> List[List[str]]:
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SHELL_OPERATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _contains_atomic_launcher_token(command: str) -> bool:
    tokens, parsed_cleanly = _shell_tokens(command)
    if parsed_cleanly and any(
            _command_basename(token)
            == "ros1_camera_only_atomic_launcher.py" for token in tokens):
        return True
    return "ros1_camera_only_atomic_launcher.py" in command


def _atomic_camera_command_contract_failures(command: str) -> List[str]:
    """Validate a copyable atomic command against the production CLI schema."""
    tokens, parsed_cleanly = _shell_tokens(command)
    if not parsed_cleanly:
        return ["atomic_cli_parse_error"]
    segments = _token_segments(tokens)
    if len(segments) != 1:
        return ["atomic_cli_segment_count_invalid"]
    argv = segments[0]
    prefix_length = len(ATOMIC_CAMERA_EXEC_PREFIX)
    if tuple(argv[:prefix_length]) != ATOMIC_CAMERA_EXEC_PREFIX:
        return ["atomic_cli_execution_prefix_mismatch"]
    option_roles = {
        "--mode": "mode",
        "--actual-vendor-launch": "actual_vendor_launch",
    }
    values: Dict[str, str] = {}
    index = prefix_length
    while index < len(argv):
        option = argv[index]
        role = option_roles.get(option)
        if role is None:
            if option.startswith("-"):
                return ["atomic_cli_unknown_argument"]
            return ["atomic_cli_unexpected_positional_argument"]
        if role in values:
            return ["atomic_cli_duplicate_argument:" + role]
        if index + 1 >= len(argv) or argv[index + 1] in option_roles:
            return ["atomic_cli_missing_argument_value:" + role]
        value = argv[index + 1]
        if not value or value.startswith("--"):
            return ["atomic_cli_missing_argument_value:" + role]
        values[role] = value
        index += 2
    for option in ATOMIC_CAMERA_REQUIRED_OPTIONS:
        role = option_roles[option]
        if role not in values:
            return ["atomic_cli_missing_argument:" + role]
        if values[role] != ATOMIC_CAMERA_OPTION_VALUES[option]:
            return ["atomic_cli_argument_value_mismatch:" + role]
    return []


def _skip_wrapper_options(
        wrapper: str, tokens: Sequence[str], index: int) -> int:
    options_with_values = _WRAPPER_OPTIONS_WITH_VALUES.get(wrapper, set())
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if wrapper == "env" and _SHELL_ASSIGNMENT.fullmatch(token):
            index += 1
            continue
        if not token.startswith("-") or token == "-":
            break
        option = token.split("=", 1)[0]
        index += 1
        if ("=" not in token and option in options_with_values
                and index < len(tokens)):
            index += 1
    return index


def _env_split_command(tokens: Sequence[str], index: int) -> str | None:
    for option_index in range(index + 1, len(tokens)):
        option = tokens[option_index]
        if option in {"-S", "--split-string"}:
            if option_index + 1 < len(tokens):
                return tokens[option_index + 1]
            return ""
        if option.startswith("--split-string="):
            return option.split("=", 1)[1]
    return None


def _segment_command_positions(
        tokens: Sequence[str],
        wrapper_chain: Sequence[str] = (),
        depth: int = 0,
        ) -> List[Dict[str, Any]]:
    if depth > 4:
        return []
    index = 0
    while index < len(tokens):
        if _SHELL_ASSIGNMENT.fullmatch(tokens[index]):
            index += 1
            continue
        if tokens[index] in _SHELL_CONTROL_PREFIXES:
            index += 1
            continue
        if tokens[index] in _SHELL_CONTROL_TERMINATORS:
            return []
        break
    wrappers = list(wrapper_chain)
    while index < len(tokens):
        command_token = tokens[index]
        if _is_dynamic_command_token(command_token):
            return []
        command_name = _command_basename(command_token)
        if command_name == "env":
            split_command = _env_split_command(tokens, index)
            if split_command is not None:
                nested_tokens, parsed_cleanly = _shell_tokens(split_command)
                if not parsed_cleanly or not nested_tokens:
                    return []
                positions: List[Dict[str, Any]] = []
                for segment in _token_segments(nested_tokens):
                    positions.extend(_segment_command_positions(
                        segment, (*wrappers, "env"), depth + 1))
                return positions
        if command_name in _COMMAND_WRAPPERS:
            wrappers.append(command_name)
            index = _skip_wrapper_options(command_name, tokens, index + 1)
            index += min(
                _WRAPPER_POSITIONAL_PREFIX_COUNTS.get(command_name, 0),
                max(0, len(tokens) - index))
            while (index < len(tokens)
                   and _SHELL_ASSIGNMENT.fullmatch(tokens[index])):
                index += 1
            continue
        if command_name in {"bash", "sh"}:
            command_index = None
            for option_index in range(index + 1, len(tokens)):
                option = tokens[option_index]
                if option == "--":
                    continue
                if option.startswith("-") and "c" in option[1:]:
                    command_index = option_index + 1
                    break
                if not option.startswith("-"):
                    break
            if command_index is not None and command_index < len(tokens):
                nested = tokens[command_index]
                nested_tokens, parsed_cleanly = _shell_tokens(nested)
                if not parsed_cleanly:
                    return []
                positions: List[Dict[str, Any]] = [{
                    "actual_command": command_name,
                    "arguments": list(tokens[index + 1:]),
                    "normalized": shlex.join(list(tokens)),
                    "wrapper_chain": wrappers,
                }]
                for segment in _token_segments(nested_tokens):
                    positions.extend(_segment_command_positions(
                        segment, (*wrappers, command_name), depth + 1))
                return positions
        position = {
            "actual_command": command_name,
            "arguments": list(tokens[index + 1:]),
            "normalized": shlex.join(list(tokens)),
            "wrapper_chain": wrappers,
        }
        if _surfaces_for_position(position):
            return [position]
        if command_name in _NON_EXECUTING_LITERAL_COMMANDS:
            return [position]
        unproven_chain = (*wrappers, "unproven:" + command_name)
        for candidate_index in range(index + 1, len(tokens)):
            candidate = tokens[candidate_index]
            if _is_dynamic_command_token(candidate):
                continue
            if any(character.isspace() for character in candidate):
                nested_tokens, parsed_cleanly = _shell_tokens(candidate)
                if not parsed_cleanly:
                    continue
            else:
                nested_tokens = list(tokens[candidate_index:])
            nested_positions: List[Dict[str, Any]] = []
            for segment in _token_segments(nested_tokens):
                nested_positions.extend(_segment_command_positions(
                    segment, unproven_chain, depth + 1))
            risk_positions = [
                item for item in nested_positions
                if _surfaces_for_position(item)]
            if risk_positions:
                return risk_positions
        return [position]
    return []


def _surfaces_for_position(position: Dict[str, Any]) -> Tuple[str, ...]:
    actual = position["actual_command"]
    arguments = position["arguments"]
    if actual == "ros2":
        index = 0
        while index < len(arguments) and arguments[index].startswith("-"):
            option = arguments[index].split("=", 1)[0]
            index += 1
            if ("=" not in arguments[index - 1]
                    and option in _ROS2_GLOBAL_OPTIONS_WITH_VALUES
                    and index < len(arguments)):
                index += 1
        if index >= len(arguments):
            return ("ros2_other",)
        subcommand = arguments[index].lower()
        if subcommand in _ROS2_SUBCOMMANDS:
            return ("ros2_" + subcommand,)
        return ("ros2_other",)
    if actual == "rosbag2":
        return ("rosbag2",)
    if actual == "colcon":
        return ("colcon",)
    if actual in {"source", "."} and arguments:
        source_path = "/" + arguments[0].lstrip("/")
        normalized_source = posixpath.normpath(source_path)
        match = re.match(
            r"^/opt/ros/(foxy|humble)(?:/|$)",
            normalized_source, re.IGNORECASE)
        if match:
            return ("source_ros2_" + match.group(1).lower(),)
    if actual in _SHELL_META_COMMANDS:
        return ("shell_" + actual,)
    if actual in {"bash", "sh"}:
        if not arguments:
            return ("shell_interactive_execution",)
        if any(
                option.startswith("-") and "c" in option[1:]
                for option in arguments):
            return ("shell_inline_execution",)
        if "-s" in arguments or "--stdin" in arguments:
            return ("shell_stdin_execution",)
        return ("shell_script_execution",)
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", actual):
        if "-c" in arguments:
            return ("python_inline_execution",)
        if "-m" in arguments:
            module_index = arguments.index("-m") + 1
            if (module_index < len(arguments)
                    and (arguments[module_index] == "ros2cli"
                         or arguments[module_index].startswith("ros2cli."))):
                return ("python_ros2cli_module",)
    if actual in {"make", "ninja"}:
        return ("build_tool_execution",)
    return ()


def _classify_operational_commands(
        command: str) -> Tuple[List[Dict[str, Any]], bool]:
    underlying, _ = _strip_legacy_marker(command)
    tokens, parsed_cleanly = _shell_tokens(underlying)
    if not parsed_cleanly:
        return [], False
    classifications: List[Dict[str, Any]] = []
    for segment in _token_segments(tokens):
        for position in _segment_command_positions(segment):
            surfaces = _surfaces_for_position(position)
            if surfaces:
                classifications.append({**position, "surfaces": surfaces})
    return classifications, True


def _legacy_operational_surfaces(command: str) -> Tuple[str, ...]:
    classifications, _ = _classify_operational_commands(command)
    return tuple(dict.fromkeys(
        surface
        for item in classifications
        for surface in item["surfaces"]))


def _is_dynamic_command_token(token: str) -> bool:
    return any(character in token for character in ("$", "`", "*", "?"))


def _segment_has_dynamic_command_position(tokens: Sequence[str]) -> bool:
    index = 0
    while index < len(tokens):
        if (_SHELL_ASSIGNMENT.fullmatch(tokens[index])
                or tokens[index] in _SHELL_CONTROL_PREFIXES):
            index += 1
            continue
        if tokens[index] in _SHELL_CONTROL_TERMINATORS:
            return False
        break
    while index < len(tokens):
        command_token = tokens[index]
        if _is_dynamic_command_token(command_token):
            return True
        command_name = _command_basename(command_token)
        remainder = list(tokens[index + 1:])
        if command_name in {"source", "."}:
            return any(_is_dynamic_command_token(token) for token in remainder)
        if command_name in _COMMAND_WRAPPERS:
            if any(_is_dynamic_command_token(token) for token in remainder):
                return True
            index = _skip_wrapper_options(command_name, tokens, index + 1)
            index += min(
                _WRAPPER_POSITIONAL_PREFIX_COUNTS.get(command_name, 0),
                max(0, len(tokens) - index))
            continue
        if command_name in {"bash", "sh"}:
            for option_index, option in enumerate(remainder):
                if option.startswith("-") and "c" in option[1:]:
                    command_index = option_index + 1
                    if command_index >= len(remainder):
                        return True
                    nested = remainder[command_index]
                    if _is_dynamic_command_token(nested):
                        return True
                    return _has_dynamic_command_position(nested)
        if command_name == "eval":
            return bool(remainder)
        return False
    return False


def _has_dynamic_command_position(command: str) -> bool:
    tokens, parsed_cleanly = _shell_tokens(command)
    if not parsed_cleanly:
        return False
    segment: List[str] = []
    for token in tokens + [";"]:
        if token in _SHELL_OPERATORS:
            if segment and _segment_has_dynamic_command_position(segment):
                return True
            segment = []
        else:
            segment.append(token)
    return False


def _read_regular_unlinked_file(
        root: Path, relative_path: str) -> Tuple[bytes | None, List[str]]:
    failures: List[str] = []
    path = root.joinpath(*Path(relative_path).parts)
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            failures.append("operator_doc_support_artifact_not_regular:" + relative_path)
            return None, failures
        if before.st_nlink != 1:
            failures.append("operator_doc_support_artifact_linklike:" + relative_path)
            return None, failures
        raw = path.read_bytes()
        after = os.lstat(path)
    except OSError:
        failures.append("operator_doc_support_artifact_unavailable:" + relative_path)
        return None, failures
    stable_fields = (
        before.st_dev == after.st_dev,
        before.st_ino == after.st_ino,
        before.st_size == after.st_size == len(raw),
        before.st_mtime_ns == after.st_mtime_ns,
        before.st_nlink == after.st_nlink == 1,
        stat.S_ISREG(after.st_mode),
    )
    if not all(stable_fields):
        failures.append("operator_doc_support_artifact_identity_drift:" + relative_path)
        return None, failures
    return raw, failures


def _validate_hardware_readiness_redirect(
        root: Path) -> Tuple[bool, List[str], Dict[str, Any] | None]:
    failures: List[str] = []
    redirect_raw, read_failures = _read_regular_unlinked_file(
        root, HARDWARE_READINESS_REDIRECT)
    failures.extend(read_failures)
    artifact = None
    if redirect_raw is not None:
        identity = {
            "size_bytes": len(redirect_raw),
            "sha256": _sha256(redirect_raw),
        }
        artifact = {
            "role": "operator_document_demotion_redirect",
            "path": HARDWARE_READINESS_REDIRECT,
            **identity,
        }
        if identity != HARDWARE_REDIRECT_IDENTITY:
            failures.append("hardware_readiness_redirect_identity_invalid")
        try:
            redirect_text = redirect_raw.decode("utf-8", errors="strict")
        except UnicodeError:
            failures.append("hardware_readiness_redirect_utf8_invalid")
        else:
            required = (
                "NON_AUTHORITATIVE_DO_NOT_RUN",
                "current field authority is ROS1 / Noetic",
                "path: `docs/hardware_readiness.md`",
                "size_bytes: `13274`",
                "sha256: `6d48815b660c3f6b0c00fb36dc633d403b540e5a95f0bdedaddc37f33093fd9b`",
                "docs/PERCEPTION_V2_ROS1_NOETIC_FIELD_RUNBOOK.md",
                "audit_tools/ros1_camera_only_atomic_launcher.py",
                "not a\nrelease-selection authority",
            )
            if any(token not in redirect_text for token in required):
                failures.append("hardware_readiness_redirect_contract_invalid")

    target_raw, target_failures = _read_regular_unlinked_file(
        root, HARDWARE_READINESS_DOCUMENT)
    failures.extend(target_failures)
    if target_raw is not None and {
            "size_bytes": len(target_raw),
            "sha256": _sha256(target_raw),
            } != HARDWARE_READINESS_IDENTITY:
        failures.append("hardware_readiness_redirect_target_identity_invalid")
    return not failures, failures, artifact


def _validate_legacy_camera_template(text: str) -> List[str]:
    """Require the retired ROS2 worksheet to remain visibly non-executable."""
    failures: List[str] = []
    lines = tuple(text.splitlines())
    if lines[:len(LEGACY_CAMERA_TEMPLATE_HEADER)] != (
            LEGACY_CAMERA_TEMPLATE_HEADER):
        failures.append("legacy_camera_template_demotion_banner_invalid")
    if _LEGACY_TEMPLATE_SHELL_FENCE.search(text):
        failures.append("legacy_camera_template_shell_fence_present")
    for number, line, _ in _copyable_lines(text):
        if line and not line.startswith(HISTORICAL_PREFIX):
            failures.append(
                "legacy_camera_template_copyable_command_not_demoted:"
                "{}:{}".format(LEGACY_CAMERA_TEMPLATE, number))
    if _LEGACY_TEMPLATE_PROMOTION.search(text) or any(
            token in text for token in (
                "authorizes_field_delivery=true",
                "delivery_ready=true",
                "formal_consumer=true",
            )):
        failures.append("legacy_camera_template_historical_pass_promoted")
    return failures


def _scan_document_report(
        relative_path: str,
        text: str,
        require_complete_historical_inventory: bool = False,
        document_demoted: bool = False,
        ) -> Dict[str, Any]:
    commands, parse_failures = _logical_shell_commands(text)
    failures = list(parse_failures)
    observed_roles: List[Dict[str, Any]] = []
    if relative_path == LEGACY_CAMERA_TEMPLATE:
        template_failures = _validate_legacy_camera_template(text)
        failures.extend(template_failures)
        document_demoted = document_demoted or not template_failures
    for number, line in _non_shell_fence_lines(text):
        classifications, operational_parsed = (
            _classify_operational_commands(line))
        if line and not operational_parsed:
            failures.append(
                "operator_doc_non_shell_fence_parse_failed:{}:{}".format(
                    relative_path, number))
        for classification in classifications:
            _, marked = _strip_legacy_marker(line)
            demoted = document_demoted or marked
            observed_roles.append(_legacy_role_record(
                relative_path, number, line, classification,
                document_demoted,
                "non_shell_fence"))
            if not demoted:
                failures.append(
                    "operator_doc_legacy_surface_not_demoted:{}:{}:{}".format(
                        relative_path, number,
                        ",".join(classification["surfaces"])))
        contains_roslaunch, parsed_cleanly = _contains_roslaunch_token(line)
        if _has_dynamic_command_position(line):
            failures.append(
                "operator_doc_non_shell_fence_dynamic_command_position:"
                "{}:{}".format(relative_path, number))
        if (contains_roslaunch
                or (not parsed_cleanly and _ROSLAUNCH_TOKEN.search(line))
                or "ros1_camera_only_atomic_launcher.py" in line
                or _contains_retired_script_token(line)):
            failures.append(
                "operator_doc_non_shell_fence_launch_surface:{}:{}".format(
                    relative_path, number))
    expected_historical = EXPECTED_HISTORICAL_COMMANDS_BY_DOCUMENT.get(
        relative_path, ())
    observed_historical = tuple(
        command for _, command in commands
        if command.startswith(HISTORICAL_PREFIX))
    expected_positions = {
        command: index for index, command in enumerate(expected_historical)
    }
    observed_positions = [
        expected_positions.get(command, -1)
        for command in observed_historical
    ]
    historical_inventory_invalid = (
        any(position < 0 for position in observed_positions)
        or len(observed_historical) != len(set(observed_historical))
        or observed_positions != sorted(observed_positions)
        or (require_complete_historical_inventory
            and observed_historical != expected_historical)
    )
    if historical_inventory_invalid:
        failures.append(
            "operator_doc_historical_inventory_invalid:" + relative_path)
    if (relative_path == AUTHORITY_RUNBOOK
            and observed_historical != AUTHORITY_HISTORICAL_LINES):
        failures.append("authority_runbook_historical_marker_invalid")
    for number, command in commands:
        classifications, operational_parsed = (
            _classify_operational_commands(command))
        _, marked = _strip_legacy_marker(command)
        for classification in classifications:
            demoted = document_demoted or marked
            observed_roles.append(_legacy_role_record(
                relative_path, number, command, classification,
                document_demoted,
                "shell_command"))
            if not demoted:
                failures.append(
                    "operator_doc_legacy_surface_not_demoted:{}:{}:{}".format(
                        relative_path, number,
                        ",".join(classification["surfaces"])))
        if command.startswith((
                HISTORICAL_PREFIX, LEGACY_NONAUTHORITATIVE_PREFIX)):
            if not operational_parsed:
                failures.append(
                    "operator_doc_shell_parse_failed:{}:{}".format(
                        relative_path, number))
            continue
        contains_roslaunch, parsed_cleanly = _contains_roslaunch_token(command)
        if not parsed_cleanly:
            failures.append(
                "operator_doc_shell_parse_failed:{}:{}".format(
                    relative_path, number))
            continue
        contains_atomic_launcher = _contains_atomic_launcher_token(command)
        contains_retired_script = _contains_retired_script_token(command)
        if (_has_dynamic_command_position(command)
                and not contains_roslaunch
                and not contains_atomic_launcher
                and not contains_retired_script):
            failures.append(
                "operator_doc_dynamic_command_position:{}:{}".format(
                    relative_path, number))
        if contains_roslaunch:
            if _FORMAL_CAPTURE_ROLE.fullmatch(command):
                observed_roles.append({
                    "role": "FORMAL_DETECTOR_CAPTURE",
                    "path": relative_path,
                    "line": number,
                    "command": command,
                    "normalized": _normalized_command(command),
                    "surfaces": ["ros1_formal_capture"],
                    "source_kind": "shell_command",
                })
            else:
                failures.append(
                    "operator_doc_roslaunch_role_not_allowlisted:{}:{}".format(
                        relative_path, number))
        if contains_atomic_launcher:
            atomic_contract_failures = (
                _atomic_camera_command_contract_failures(command))
            if atomic_contract_failures:
                failures.extend(
                    "{}:{}:{}".format(code, relative_path, number)
                    for code in atomic_contract_failures)
            elif _ATOMIC_CAMERA_ROLE.fullmatch(command):
                observed_roles.append({
                    "role": "ATOMIC_CAMERA_DRIVER",
                    "path": relative_path,
                    "line": number,
                    "command": command,
                    "normalized": _normalized_command(command),
                    "surfaces": ["atomic_camera_launcher"],
                    "source_kind": "shell_command",
                })
            else:
                failures.append(
                    "operator_doc_atomic_role_not_allowlisted:{}:{}".format(
                        relative_path, number))
        if contains_retired_script:
            failures.append(
                "operator_doc_retired_start_script_invocation:{}:{}".format(
                    relative_path, number))

    if relative_path == AUTHORITY_RUNBOOK:
        if "The only production camera-start entry is the host-owned atomic launcher" not in text:
            failures.append("authority_runbook_atomic_entry_declaration_missing")
    return {
        "failures": failures,
        "observed_roles": observed_roles,
        "logical_command_count": len(commands),
    }


def scan_document_text(relative_path: str, text: str) -> List[str]:
    return list(_scan_document_report(relative_path, text)["failures"])


def scan_retired_script_text(text: str) -> List[str]:
    failures: List[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != RETIRED_SCRIPT_SHEBANG:
        failures.append("retired_start_script_shebang_invalid")
    executable_commands = tuple(
        line.strip() for line in lines
        if line.strip() and not line.lstrip().startswith("#"))
    if executable_commands != RETIRED_SCRIPT_ALLOWED_COMMANDS:
        failures.append("retired_start_script_command_inventory_invalid")
    required = (
        "is retired and never starts ROS",
        "ros1_camera_only_atomic_launcher.py",
        "exit 64",
    )
    for token in required:
        if token not in text:
            failures.append("retired_start_script_required_token_missing:" + token)
    forbidden = (
        "exec roslaunch", "roslaunch astra_camera", "source ",
        "sha256sum", "$@",
    )
    for token in forbidden:
        if token in text:
            failures.append("retired_start_script_executable_token:" + token)
    return failures


def evaluate_operator_docs(workspace_root: Path) -> Dict[str, Any]:
    root = workspace_root.resolve(strict=True)
    failures: List[str] = []
    artifacts: List[Dict[str, Any]] = []
    observed_roles: List[Dict[str, Any]] = []
    redirect_valid, redirect_failures, redirect_artifact = (
        _validate_hardware_readiness_redirect(root))
    failures.extend(redirect_failures)
    if redirect_artifact is not None:
        artifacts.append(redirect_artifact)
    for relative in OPERATIONAL_DOCUMENTS:
        path = root.joinpath(*Path(relative).parts)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeError):
            failures.append("operator_doc_unavailable:" + relative)
            continue
        document_report = _scan_document_report(
            relative, text, require_complete_historical_inventory=True,
            document_demoted=(
                relative == HARDWARE_READINESS_DOCUMENT
                and redirect_valid))
        failures.extend(document_report["failures"])
        observed_roles.extend(document_report["observed_roles"])
        artifacts.append({
            "role": "operator_document",
            "path": relative,
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
        })
    script_path = root.joinpath(*Path(RETIRED_SCRIPT).parts)
    try:
        script_raw = script_path.read_bytes()
        script_text = script_raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeError):
        failures.append("retired_start_script_unavailable")
    else:
        failures.extend(scan_retired_script_text(script_text))
        artifacts.append({
            "role": "retired_start_script",
            "path": RETIRED_SCRIPT,
            "size_bytes": len(script_raw),
            "sha256": _sha256(script_raw),
        })
    formal_roles = [
        item for item in observed_roles
        if item["role"] == "FORMAL_DETECTOR_CAPTURE"]
    atomic_roles = [
        item for item in observed_roles
        if item["role"] == "ATOMIC_CAMERA_DRIVER"]
    legacy_roles = [
        item for item in observed_roles
        if item["role"] == "LEGACY_NONAUTHORITATIVE"]
    unapproved_roles = [
        item for item in observed_roles
        if item["role"] == "UNAPPROVED_OPERATIONAL_COMMAND"]
    if len(formal_roles) != 1 or formal_roles[0]["path"] != AUTHORITY_RUNBOOK:
        failures.append("formal_capture_role_observation_mismatch")
    if len(atomic_roles) != 1 or atomic_roles[0]["path"] != AUTHORITY_RUNBOOK:
        failures.append("atomic_camera_role_observation_mismatch")
    unique_failures = sorted(set(failures))
    formal_allowlisted = (
        len(formal_roles) == 1
        and formal_roles[0]["path"] == AUTHORITY_RUNBOOK
        and not unique_failures)
    atomic_allowlisted = (
        len(atomic_roles) == 1
        and atomic_roles[0]["path"] == AUTHORITY_RUNBOOK
        and not unique_failures)
    return {
        "schema_version": SCHEMA_VERSION,
        "validated_pass": not unique_failures,
        "failures": unique_failures,
        "documents_expected": list(OPERATIONAL_DOCUMENTS),
        "artifacts": artifacts,
        "observed_roles": observed_roles,
        "legacy_non_authoritative_count": len(legacy_roles),
        "unapproved_operational_command_count": len(unapproved_roles),
        "hardware_readiness_redirect_validated": redirect_valid,
        "formal_capture_role_allowlisted": formal_allowlisted,
        "atomic_camera_role_allowlisted": atomic_allowlisted,
        "authorizes_motion": False,
        "authorizes_field_delivery": False,
        "formal_consumer": False,
        "delivery_ready": False,
    }


def main(args: Sequence[str] | None = None) -> int:
    if args:
        raise SystemExit("no arguments accepted")
    workspace = Path(__file__).resolve().parents[1]
    report = evaluate_operator_docs(workspace)
    sys.stdout.write(MARKER + json.dumps(
        report, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if report["validated_pass"] else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
