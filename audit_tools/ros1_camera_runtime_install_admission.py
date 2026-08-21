"""Host-owned ROS1/Noetic camera runtime install admission.

This gate is intentionally separate from both the inert camera preflight and
the future atomic launcher.  It reopens one externally anchored authority,
then independently validates the exact Noetic ``roslaunch`` script, its
shebang interpreter, a fixed Python module closure, and the Astra package,
launch and resolved node executable.  It also derives a clean exec environment
from an empty mapping; ambient process variables are never copied.

The gate performs no ROS imports, starts no process, joins no ROS graph and
touches no camera or hardware.  A test-only filesystem may prove the validator
algorithm, but can never validate a production install or authorize launch,
field evidence, motion, or delivery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import types
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import urllib.parse
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "ros1_camera_runtime_install_admission/v1"
GATE_ID = "ROS1_NOETIC_CAMERA_RUNTIME_INSTALL_ADMISSION_V1"
AUTHORITY_MARKER = "LIMO_ROS1_CAMERA_RUNTIME_INSTALL_AUTHORITY_V1"
CLI_MARKER = "ROS1_CAMERA_RUNTIME_INSTALL_ADMISSION "
SCOPE = "ros1_noetic_camera_runtime_install"
TEST_ONLY_MODE = "test_only_validator_fixture"
PRODUCTION_MODE = "production_camera_runtime_install"

NOETIC_PREFIX = "/opt/ros/noetic"
SYSTEM_PREFIX = "/usr"
VENDOR_PREFIX = "/opt/limo/ros1_camera_runtime"
STATE_PREFIX = "/var/lib/limo_camera_runtime"
ROSLAUNCH_PATH = "/opt/ros/noetic/bin/roslaunch"
PYTHON_ENTRY_PATH = "/usr/bin/python3"
PYTHON_TARGET_PATH = "/usr/bin/python3.8"
PYTHON_ENTRY_LINK_TEXT = "python3.8"
PYTHON_VERSION = "3.8.10"
ASTRA_PACKAGE_ROOT = VENDOR_PREFIX + "/share/astra_camera"
ASTRA_PACKAGE_XML = ASTRA_PACKAGE_ROOT + "/package.xml"
ASTRA_LAUNCH_PATH = ASTRA_PACKAGE_ROOT + "/launch/dabai_u3.launch"
ASTRA_NODE_PATH = VENDOR_PREFIX + "/lib/astra_camera/astra_camera_node"
DABAI_REFERENCE_SIZE_BYTES = 6446
DABAI_REFERENCE_SHA256 = (
    "75f9ada995ac961d0b4dddb7d86d591f57dc5392165663f4a905709a24231b2e")
ROS_MASTER_URI = "http://127.0.0.1:11371/"
EXEC_ENV_POLICY_ID = "ROS1_NOETIC_CAMERA_ONLY_CLEAN_EXEC_ENV_V1"

# A production authority must be selected by host-owned source bytes, not by
# caller-supplied path/hash pairs.  These values deliberately remain unset
# until a real Noetic installation is inspected and a new source/evidence
# generation freezes its authority.  Tests use the private owner seam below;
# that seam can only validate an explicitly test-only authority and can never
# set ``validated_pass`` or any field/delivery authorization.
PRODUCTION_AUTHORITY_PATH = "/etc/limo/camera_runtime_install_authority.json"
PRODUCTION_AUTHORITY_SIZE_BYTES: Optional[int] = None
PRODUCTION_AUTHORITY_SHA256: Optional[str] = None

RUNTIME_IMPORT_PROBE_FILENAME = "ros1_camera_runtime_import_probe.py"
RUNTIME_IMPORT_PROBE_SIZE_BYTES = 78846
RUNTIME_IMPORT_PROBE_SHA256 = (
    "1eadbef39e3fbfc485109543a9ba6fba286ce9330d5fda12f38a3deac1b63141")
RUNTIME_IMPORT_PROBE_PRIVATE_MODULE = (
    "_limo_host_owned_ros1_camera_runtime_import_probe_v1")
RUNTIME_IMPORT_ASSET_ROLES = (
    "package_xml", "launch", "node_executable")
RUNTIME_IMPORT_REQUIRED_TREE_FILES = {
    "catkin_pkg": {"__init__.py"},
    "rosgraph": {"__init__.py"},
    "roslaunch": {"__init__.py", "core.py"},
    "roslib": {"__init__.py"},
    "rospkg": {"__init__.py"},
    "yaml": {"__init__.py"},
}

ROOT_ROLES = ("noetic", "system", "vendor", "state")
IMMUTABLE_EXECUTION_ROLES = {"noetic", "system", "vendor"}
ROOT_PATHS = {
    "noetic": NOETIC_PREFIX,
    "system": SYSTEM_PREFIX,
    "vendor": VENDOR_PREFIX,
    "state": STATE_PREFIX,
}
MODULE_PATHS = {
    "catkin_pkg": "/usr/lib/python3/dist-packages/catkin_pkg/__init__.py",
    "rosgraph": (
        "/opt/ros/noetic/lib/python3/dist-packages/rosgraph/__init__.py"),
    "roslaunch": (
        "/opt/ros/noetic/lib/python3/dist-packages/roslaunch/__init__.py"),
    "roslib": "/opt/ros/noetic/lib/python3/dist-packages/roslib/__init__.py",
    "rospkg": "/usr/lib/python3/dist-packages/rospkg/__init__.py",
    "yaml": "/usr/lib/python3/dist-packages/yaml/__init__.py",
}
PATH_ENTRIES = ("/opt/ros/noetic/bin", "/usr/bin")
PYTHONPATH_ENTRIES = (
    "/opt/ros/noetic/lib/python3/dist-packages",
    "/usr/lib/python3/dist-packages",
)
ROS_PACKAGE_PATH_ENTRIES = (
    VENDOR_PREFIX + "/share", "/opt/ros/noetic/share")
LD_LIBRARY_PATH_ENTRIES = (
    VENDOR_PREFIX + "/lib",
    "/opt/ros/noetic/lib",
)
CMAKE_PREFIX_PATH_ENTRIES = (VENDOR_PREFIX, NOETIC_PREFIX)
STATE_SUBDIRECTORIES = ("home", "ros-home", "log", "tmp")
SENSITIVE_AMBIENT_KEYS = (
    "PYTHONPATH", "PYTHONHOME", "ROS_PACKAGE_PATH", "ROS_MASTER_URI",
    "ROS_IP", "ROS_HOSTNAME", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "CMAKE_PREFIX_PATH", "PATH",
)
FORBIDDEN_AMBIENT_KEYS = {
    "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "CMAKE_PREFIX_PATH",
}

IDENTITY_KEYS = {"path", "size_bytes", "sha256"}
ROOT_KEYS = {"role", "path", "owner_uid"}
AUTHORITY_KEYS = {
    "schema_version", "marker", "admission_id", "scope", "test_only",
    "read_only", "authorizes_motion", "publishes_ros_messages",
    "runtime_family", "ros_distro", "trusted_install_roots", "roslaunch",
    "astra_camera", "exec_environment", "runtime_import_probe",
}
ROSLAUNCH_KEYS = {
    "executable", "shebang_interpreter_entry",
    "shebang_interpreter_link_text", "python_executable_target",
    "python_version", "module_closure",
}
RUNTIME_IMPORT_PROBE_KEYS = {
    "probe_source_identity", "module_specs", "package_trees",
    "python_root_inventories", "customization_inventory",
    "aux_executable_closure",
}
MODULE_SPEC_KEYS = {"identity", "loader_kind", "expected_version"}
PACKAGE_TREE_KEYS = {"root_path", "files"}
PYTHON_ROOT_INVENTORY_KEYS = {"root_path", "directories", "files"}
RUNTIME_IMPORT_PROBE_REPORT_KEYS = {
    "schema_version", "gate_id", "admission_mode", "read_only",
    "starts_ros_graph", "opens_camera", "runs_inference",
    "authorizes_motion", "publishes_ros_messages", "algorithm_validated",
    "validator_unit_test_pass", "validated_pass", "runtime_import_probe_pass",
    "formal_consumer", "field_evidence_admitted", "delivery_ready", "argv",
    "expected_ids", "executed_ids", "request_identity", "child_marker",
    "parent_environment_restored", "failures",
}
RUNTIME_IMPORT_CHILD_KEYS = {
    "schema_version", "marker", "request_id", "request_sha256", "status",
    "exit_code", "test_only", "algorithm_validated",
    "validator_unit_test_pass", "validated_pass",
    "runtime_import_probe_pass", "formal_consumer",
    "field_evidence_admitted", "delivery_ready", "expected_ids",
    "executed_ids", "executable_provenance", "probe_source_provenance",
    "module_provenance", "module_versions", "module_loaders",
    "package_tree_file_provenance", "customization_provenance",
    "python_root_directory_provenance", "python_root_file_provenance",
    "aux_executable_provenance", "astra_asset_provenance",
    "loaded_nonstdlib_module_ids", "child_environment_keys",
    "forbidden_environment_keys_present", "isolation",
    "sitecustomize_loaded", "failures",
}
RUNTIME_IMPORT_ISOLATION_KEYS = {
    "isolated", "no_site", "dont_write_bytecode"}
ASTRA_KEYS = {
    "package_root", "package_xml", "launch", "node_executable",
}
EXEC_ENV_KEYS = {
    "policy_id", "ros_master_uri", "state_root", "path_entries",
    "pythonpath_entries", "ros_package_path_entries",
    "ld_library_path_entries", "cmake_prefix_path_entries",
    "expected_environment_sha256",
}


class AdmissionError(RuntimeError):
    """Stable fail-closed admission error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ADMISSION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


def _reject_constant(value: str) -> None:
    raise ValueError("non_finite_json_constant:" + value)


def _strict_object(pairs: Sequence[Tuple[str, Any]]) -> Mapping[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_object,
        parse_constant=_reject_constant)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value))


def _valid_identity(value: Any, *, absolute: bool = True) -> bool:
    return (
        isinstance(value, Mapping) and set(value) == IDENTITY_KEYS
        and isinstance(value.get("path"), str) and bool(value["path"])
        and (not absolute or Path(value["path"]).is_absolute())
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] >= 0
        and _valid_sha256(value.get("sha256")))


def _snapshot(metadata: os.stat_result) -> Tuple[int, int, int, int, int, int]:
    return (
        int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_mode),
        int(metadata.st_nlink), int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _node_report(metadata: os.stat_result) -> Mapping[str, Any]:
    return {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(metadata.st_mode),
        "owner_uid": int(getattr(metadata, "st_uid", 0)),
        "group_gid": int(getattr(metadata, "st_gid", 0)),
        "nlink": int(metadata.st_nlink),
        "size_bytes": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
    }


def _is_linklike(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        reparse and getattr(metadata, "st_file_attributes", 0) & reparse)


def _logical_absolute(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise AdmissionError(code)
    pure = PurePosixPath(value)
    if not pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise AdmissionError(code)
    return pure.as_posix()


def _rooted(environment_root: Path, logical_path: str) -> Path:
    pure = PurePosixPath(_logical_absolute(logical_path, "logical_path_invalid"))
    root = Path(environment_root).resolve(strict=True)
    return root.joinpath(*pure.parts[1:])


def _safe_mode(metadata: os.stat_result) -> bool:
    return (int(metadata.st_mode) & 0o022) == 0


def _immutable_execution_mode_safe(
        metadata: os.stat_result, expected_owner_uid: int) -> bool:
    """Root-owned install trees may be 0755/0644 for a non-root runtime."""
    effective_uid = int(os.geteuid()) if hasattr(os, "geteuid") else 0
    forbidden = (
        0o022 if int(expected_owner_uid) == 0 and effective_uid != 0
        else 0o222)
    return (int(metadata.st_mode) & forbidden) == 0


def _owner(metadata: os.stat_result) -> int:
    return int(getattr(metadata, "st_uid", 0))


def _chain_from_root(root: Path, target: Path) -> List[Path]:
    root = Path(root).resolve(strict=True)
    absolute = Path(target).absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as error:
        raise AdmissionError("path_outside_environment_root") from error
    chain = [root]
    current = root
    for part in relative.parts:
        current = current / part
        chain.append(current)
    return chain


def _validate_directory_chain(
        environment_root: Path, directory: Path, allowed_owners: Sequence[int],
        code: str) -> List[Mapping[str, Any]]:
    reports: List[Mapping[str, Any]] = []
    allowed = set(int(value) for value in allowed_owners)
    try:
        chain = _chain_from_root(environment_root, directory)
        for item in chain:
            metadata = item.lstat()
            if (_is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode)
                    or _owner(metadata) not in allowed
                    or not _safe_mode(metadata)):
                raise AdmissionError(code)
            reports.append({"path": str(item), **_node_report(metadata)})
    except AdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise AdmissionError(code) from error
    return reports


def _validate_immutable_execution_directory_chain(
        trusted_root: Path, directory: Path, expected_owner_uid: int,
        code: str) -> List[Mapping[str, Any]]:
    """Validate an execution subtree whose nodes are root/read-only in prod."""
    reports: List[Mapping[str, Any]] = []
    try:
        for item in _chain_from_root(trusted_root, directory):
            metadata = item.lstat()
            if _is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise AdmissionError(code + ":not_directory_or_linklike")
            if _owner(metadata) != int(expected_owner_uid):
                raise AdmissionError(code + ":owner_mismatch")
            if not _immutable_execution_mode_safe(
                    metadata, expected_owner_uid):
                raise AdmissionError(code + ":writable")
            if int(metadata.st_mode) & 0o555 != 0o555:
                raise AdmissionError(code + ":not_searchable_readable")
            reports.append({"path": str(item), **_node_report(metadata)})
    except AdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise AdmissionError(code + ":unavailable") from error
    return reports


def _validate_runtime_state_root(
        path: Path, expected_owner_uid: int, code: str) -> Mapping[str, Any]:
    try:
        metadata = path.lstat()
        if (_is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode)
                or _owner(metadata) != int(expected_owner_uid)
                or not _safe_mode(metadata)
                or int(metadata.st_mode) & 0o700 != 0o700):
            raise AdmissionError(code)
    except AdmissionError:
        raise
    except OSError as error:
        raise AdmissionError(code) from error
    return {"path": str(path), **_node_report(metadata)}


def _read_authority_file(path: Path) -> Tuple[Mapping[str, Any], bytes]:
    """Read the external authority once and bind identity to parsed bytes."""
    candidate = Path(path)
    try:
        if not candidate.is_absolute():
            raise AdmissionError("authority_path_not_absolute")
        absolute = candidate.absolute()
        resolved = candidate.resolve(strict=True)
        chain = _chain_from_root(Path(absolute.anchor), absolute)
        for item in chain:
            metadata = item.lstat()
            if _is_linklike(metadata):
                raise AdmissionError("authority_path_linklike")
        before = resolved.lstat()
        if (not stat.S_ISREG(before.st_mode)
                or int(before.st_nlink) != 1):
            raise AdmissionError("authority_not_regular_unique_file")
        raw = resolved.read_bytes()
        after = resolved.lstat()
        if _snapshot(before) != _snapshot(after):
            raise AdmissionError("authority_changed_during_read")
        return {
            "path": str(resolved),
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
        }, raw
    except AdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise AdmissionError("authority_unavailable") from error


def regular_file_identity(path: Path) -> Mapping[str, Any]:
    """Identity for the external authority; rejects linked ancestors."""
    identity, unused_raw = _read_authority_file(path)
    return identity


def _load_exact_runtime_import_probe(
        *, production: bool) -> Tuple[Any, Mapping[str, Any]]:
    path = Path(__file__).resolve(strict=True).with_name(
        RUNTIME_IMPORT_PROBE_FILENAME)
    identity, raw = _read_authority_file(path)
    expected = {
        "path": str(path),
        "size_bytes": RUNTIME_IMPORT_PROBE_SIZE_BYTES,
        "sha256": RUNTIME_IMPORT_PROBE_SHA256,
    }
    if identity != expected:
        raise AdmissionError("runtime_import_probe_source_identity_mismatch")
    try:
        metadata = path.lstat()
        if production and (
                _owner(metadata) != 0
                or not _immutable_execution_mode_safe(metadata, 0)):
            raise AdmissionError("runtime_import_probe_source_policy_invalid")
        code = compile(raw, str(path), "exec", dont_inherit=True)
        module = types.ModuleType(RUNTIME_IMPORT_PROBE_PRIVATE_MODULE)
        module.__file__ = str(path)
        module.__package__ = ""
        module.__spec__ = None
        exec(code, module.__dict__)
    except AdmissionError:
        raise
    except BaseException as error:
        raise AdmissionError(
            "runtime_import_probe_exact_load_failed:" + type(error).__name__
        ) from error
    if (
        getattr(module, "GATE_ID", None)
        != "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1"
        or not callable(getattr(module, "run_camera_runtime_import_probe", None))
        or getattr(module, "PRODUCTION_MODE", None)
        != "production_camera_runtime_import"
        or getattr(module, "TEST_ONLY_MODE", None)
        != "test_only_validator_fixture"
        or hasattr(module, "PRODUCTION_SPEC")
        or not callable(getattr(module, "_production_spec_anchor_bound", None))
    ):
        raise AdmissionError("runtime_import_probe_api_contract_invalid")
    if regular_file_identity(path) != identity:
        raise AdmissionError("runtime_import_probe_source_changed_during_load")
    return module, identity


def _validate_authority_path_policy(
        path: Path, trusted_chain_root: Path,
        allowed_owners: Sequence[int]) -> Mapping[str, Any]:
    candidate = Path(path)
    allowed = set(int(value) for value in allowed_owners)
    _validate_directory_chain(
        trusted_chain_root, candidate.parent, tuple(allowed),
        "authority_parent_chain_invalid")
    try:
        metadata = candidate.lstat()
        if (_is_linklike(metadata) or not stat.S_ISREG(metadata.st_mode)
                or int(metadata.st_nlink) != 1
                or _owner(metadata) not in allowed
                or not _safe_mode(metadata)):
            raise AdmissionError("authority_file_policy_invalid")
    except AdmissionError:
        raise
    except OSError as error:
        raise AdmissionError("authority_file_policy_invalid") from error
    return {"path": str(candidate), **_node_report(metadata)}


def _load_authority(
        path: Path, expected_identity: Mapping[str, Any]) -> Tuple[
            Mapping[str, Any], Mapping[str, Any]]:
    if not _valid_identity(expected_identity):
        raise AdmissionError("authority_external_identity_schema_invalid")
    actual, raw = _read_authority_file(path)
    if dict(expected_identity) != actual:
        raise AdmissionError("authority_external_anchor_mismatch")
    try:
        value = _strict_json_bytes(raw)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise AdmissionError("authority_strict_json_invalid") from error
    if not isinstance(value, Mapping) or set(value) != AUTHORITY_KEYS:
        raise AdmissionError("authority_schema_invalid")
    if (value.get("schema_version") != 1
            or value.get("marker") != AUTHORITY_MARKER
            or not isinstance(value.get("admission_id"), str)
            or _ADMISSION_ID.fullmatch(value["admission_id"]) is None
            or value.get("scope") != SCOPE
            or type(value.get("test_only")) is not bool
            or value.get("read_only") is not True
            or value.get("authorizes_motion") is not False
            or value.get("publishes_ros_messages") is not False
            or value.get("runtime_family") != "ROS1"
            or value.get("ros_distro") != "noetic"):
        raise AdmissionError("authority_policy_invalid")
    return dict(value), actual


def _validate_root_declarations(
        authority: Mapping[str, Any], environment_root: Path,
        test_owner_uid: Optional[int]) -> Tuple[
            Mapping[str, Mapping[str, Any]], Mapping[str, List[Mapping[str, Any]]]]:
    declarations = authority.get("trusted_install_roots")
    if (not isinstance(declarations, list)
            or len(declarations) != len(ROOT_ROLES)):
        raise AdmissionError("trusted_root_schema_invalid")
    roots: Dict[str, Mapping[str, Any]] = {}
    reports: Dict[str, List[Mapping[str, Any]]] = {}
    production = not authority["test_only"]
    current_uid = int(os.getuid()) if hasattr(os, "getuid") else 0
    for index, role in enumerate(ROOT_ROLES):
        item = declarations[index]
        if (not isinstance(item, Mapping) or set(item) != ROOT_KEYS
                or item.get("role") != role
                or item.get("path") != ROOT_PATHS[role]
                or type(item.get("owner_uid")) is not int
                or item["owner_uid"] < 0):
            raise AdmissionError("trusted_root_schema_invalid:" + role)
        if production:
            expected_owner = (
                0 if role in IMMUTABLE_EXECUTION_ROLES else current_uid)
            if item["owner_uid"] != expected_owner:
                raise AdmissionError("trusted_root_owner_invalid:" + role)
        elif test_owner_uid is None or item["owner_uid"] != test_owner_uid:
            raise AdmissionError("trusted_root_test_owner_invalid:" + role)
        actual_path = _rooted(environment_root, item["path"])
        allowed = (0, item["owner_uid"])
        if role in IMMUTABLE_EXECUTION_ROLES:
            outer = _validate_directory_chain(
                environment_root, actual_path.parent, allowed,
                "trusted_root_outer_chain_invalid:" + role)
            inner = _validate_immutable_execution_directory_chain(
                actual_path, actual_path, item["owner_uid"],
                "trusted_root_immutable_invalid:" + role)
            reports[role] = outer + inner
        else:
            reports[role] = _validate_directory_chain(
                environment_root, actual_path, allowed,
                "trusted_root_chain_invalid:" + role)
            reports[role].append(_validate_runtime_state_root(
                actual_path, item["owner_uid"],
                "trusted_state_root_policy_invalid"))
        roots[role] = {
            "role": role,
            "declaration": dict(item),
            "actual_path": actual_path,
            "allowed_owners": allowed,
            "expected_owner_uid": item["owner_uid"],
            "immutable_execution": role in IMMUTABLE_EXECUTION_ROLES,
        }
    return roots, reports


def _root_for_logical(
        logical_path: str, roots: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    matches = []
    pure = PurePosixPath(logical_path)
    for role, record in roots.items():
        root = PurePosixPath(record["declaration"]["path"])
        try:
            pure.relative_to(root)
        except ValueError:
            continue
        matches.append((len(root.parts), role, record))
    if not matches:
        raise AdmissionError("artifact_outside_trusted_roots")
    return max(matches, key=lambda item: item[0])[2]


def _validate_artifact_parent_chain(
        environment_root: Path, parent: Path,
        root_record: Mapping[str, Any], code: str
        ) -> List[Mapping[str, Any]]:
    if root_record.get("immutable_execution") is True:
        return _validate_immutable_execution_directory_chain(
            root_record["actual_path"], parent,
            root_record["expected_owner_uid"], code)
    return _validate_directory_chain(
        environment_root, parent, root_record["allowed_owners"], code)


def _validate_file(
        declaration: Any, environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]], label: str,
        *, executable: bool = False, expected_path: Optional[str] = None
        ) -> Tuple[Mapping[str, Any], bytes, Path]:
    if not _valid_identity(declaration, absolute=True):
        raise AdmissionError("artifact_identity_schema_invalid:" + label)
    logical = _logical_absolute(
        declaration["path"], "artifact_path_invalid:" + label)
    if expected_path is not None and logical != expected_path:
        raise AdmissionError("artifact_exact_path_mismatch:" + label)
    root_record = _root_for_logical(logical, roots)
    path = _rooted(environment_root, logical)
    _validate_artifact_parent_chain(
        environment_root, path.parent, root_record,
        "artifact_parent_chain_invalid:" + label)
    try:
        before = path.lstat()
        immutable = root_record.get("immutable_execution") is True
        owner_valid = (
            _owner(before) == int(root_record["expected_owner_uid"])
            if immutable
            else _owner(before) in set(root_record["allowed_owners"]))
        mode_valid = (
            _immutable_execution_mode_safe(
                before, int(root_record["expected_owner_uid"]))
            if immutable else _safe_mode(before))
        if (_is_linklike(before) or not stat.S_ISREG(before.st_mode)
                or int(before.st_nlink) != 1
                or not owner_valid or not mode_valid):
            raise AdmissionError("artifact_file_policy_invalid:" + label)
        if executable and (
                int(before.st_mode) & 0o555) != 0o555:
            raise AdmissionError("artifact_not_executable:" + label)
        if immutable and not executable and (
                int(before.st_mode) & 0o444) != 0o444:
            raise AdmissionError("artifact_not_readable:" + label)
        raw = path.read_bytes()
        after = path.lstat()
        if _snapshot(before) != _snapshot(after):
            raise AdmissionError("artifact_changed_during_read:" + label)
    except AdmissionError:
        raise
    except OSError as error:
        raise AdmissionError("artifact_unavailable:" + label) from error
    actual = {
        "path": logical,
        "size_bytes": len(raw),
        "sha256": _sha256(raw),
    }
    if actual != dict(declaration):
        raise AdmissionError("artifact_identity_mismatch:" + label)
    return {
        **actual,
        "resolved_path": str(path.resolve(strict=True)),
        "filesystem_identity": _node_report(after),
    }, raw, path


def _validate_python_entry(
        roslaunch: Mapping[str, Any], environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]], target_path: Path) -> Mapping[str, Any]:
    entry_logical = roslaunch.get("shebang_interpreter_entry")
    link_text = roslaunch.get("shebang_interpreter_link_text")
    if (entry_logical != PYTHON_ENTRY_PATH
            or link_text != PYTHON_ENTRY_LINK_TEXT):
        raise AdmissionError("python_entry_declaration_invalid")
    entry = _rooted(environment_root, entry_logical)
    system = roots["system"]
    _validate_artifact_parent_chain(
        environment_root, entry.parent, system,
        "python_entry_parent_chain_invalid")
    try:
        before = entry.lstat()
        if (not stat.S_ISLNK(before.st_mode)
                or int(before.st_nlink) != 1):
            raise AdmissionError("python_entry_symlink_required")
        if _owner(before) != int(system["expected_owner_uid"]):
            raise AdmissionError("python_entry_owner_invalid")
        observed_link = os.readlink(str(entry))
        resolved = entry.resolve(strict=True)
        after = entry.lstat()
        if _snapshot(before) != _snapshot(after):
            raise AdmissionError("python_entry_changed_during_read")
    except AdmissionError:
        raise
    except (OSError, RuntimeError) as error:
        raise AdmissionError("python_entry_invalid") from error
    if observed_link != link_text or resolved != target_path.resolve(strict=True):
        raise AdmissionError("python_entry_target_mismatch")
    return {
        "entry_path": entry_logical,
        "entry_link_text": observed_link,
        "resolved_target_path": PYTHON_TARGET_PATH,
        "filesystem_identity": _node_report(after),
    }


def _validate_roslaunch(
        authority: Mapping[str, Any], environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    value = authority.get("roslaunch")
    if not isinstance(value, Mapping) or set(value) != ROSLAUNCH_KEYS:
        raise AdmissionError("roslaunch_schema_invalid")
    if value.get("python_version") != PYTHON_VERSION:
        raise AdmissionError("python_version_declaration_invalid")
    executable, raw, unused_path = _validate_file(
        value["executable"], environment_root, roots, "roslaunch_executable",
        executable=True, expected_path=ROSLAUNCH_PATH)
    target, unused_raw, target_path = _validate_file(
        value["python_executable_target"], environment_root, roots,
        "python_executable_target", executable=True,
        expected_path=PYTHON_TARGET_PATH)
    entry = _validate_python_entry(value, environment_root, roots, target_path)
    try:
        first_line = raw.splitlines()[0].decode("ascii", errors="strict")
    except (IndexError, UnicodeError) as error:
        raise AdmissionError("roslaunch_shebang_invalid") from error
    if first_line != "#!" + PYTHON_ENTRY_PATH:
        raise AdmissionError("roslaunch_shebang_invalid")
    closure = value.get("module_closure")
    if (not isinstance(closure, Mapping)
            or not set(MODULE_PATHS).issubset(set(closure))
            or any(
                not isinstance(name, str)
                or _MODULE_NAME.fullmatch(name) is None
                for name in closure)):
        raise AdmissionError("module_closure_set_invalid")
    modules = {}
    seen_paths = set()
    for name in sorted(closure):
        record, module_raw, unused_module_path = _validate_file(
            closure[name], environment_root, roots,
            "module_closure:" + name,
            expected_path=MODULE_PATHS.get(name))
        if record["path"] in seen_paths or not module_raw:
            raise AdmissionError("module_closure_artifact_invalid:" + name)
        seen_paths.add(record["path"])
        modules[name] = record
    return {
        "executable": executable,
        "shebang_interpreter": entry,
        "python_executable_target": target,
        "python_version": PYTHON_VERSION,
        "module_closure": modules,
    }


def _identity_view(record: Mapping[str, Any], *, physical: bool) -> Mapping[str, Any]:
    return {
        "path": record["resolved_path"] if physical else record["path"],
        "size_bytes": record["size_bytes"],
        "sha256": record["sha256"],
    }


def _safe_tree_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute() and ".." not in path.parts
        and "." not in path.parts and path.as_posix() == value)


def _enumerate_package_tree(
        *, logical_root: str, environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]], label: str
        ) -> Tuple[Path, Sequence[str], Sequence[str]]:
    root_record = _root_for_logical(logical_root, roots)
    physical_root = _rooted(environment_root, logical_root)
    _validate_artifact_parent_chain(
        environment_root, physical_root, root_record,
        "runtime_import_package_tree_directory_invalid:" + label)
    directories = set()
    files = set()
    try:
        for current, names, filenames in os.walk(
                str(physical_root), followlinks=False):
            current_path = Path(current)
            for name in sorted(names):
                path = current_path / name
                metadata = path.lstat()
                if _is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    raise AdmissionError(
                        "runtime_import_package_tree_linklike:" + label)
                _validate_artifact_parent_chain(
                    environment_root, path, root_record,
                    "runtime_import_package_tree_directory_invalid:" + label)
                directories.add(path.relative_to(physical_root).as_posix())
            for name in sorted(filenames):
                path = current_path / name
                metadata = path.lstat()
                if _is_linklike(metadata) or not stat.S_ISREG(metadata.st_mode):
                    raise AdmissionError(
                        "runtime_import_package_tree_linklike:" + label)
                files.add(path.relative_to(physical_root).as_posix())
    except AdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise AdmissionError(
            "runtime_import_package_tree_unavailable:" + label) from error
    expected_directories = {
        parent.as_posix()
        for relative in files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    if directories != expected_directories:
        raise AdmissionError(
            "runtime_import_package_tree_directory_set_mismatch:" + label)
    return physical_root, sorted(directories), sorted(files)


def _enumerate_exact_python_root(
        *, role: str, logical_root: str, environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]]) -> Tuple[
            Path, Mapping[str, Any], Mapping[str, Mapping[str, Any]],
            Sequence[str]]:
    label = "runtime_import_python_root_inventory:" + role
    root_record = _root_for_logical(logical_root, roots)
    physical_root = _rooted(environment_root, logical_root)
    _validate_artifact_parent_chain(
        environment_root, physical_root, root_record,
        label + ":root_invalid")
    try:
        root_before = physical_root.lstat()
        if _is_linklike(root_before) or not stat.S_ISDIR(root_before.st_mode):
            raise AdmissionError(label + ":root_invalid")
        directory_reports: Dict[str, Mapping[str, Any]] = {}
        files = set()
        for current, names, filenames in os.walk(
                str(physical_root), followlinks=False):
            names.sort()
            filenames.sort()
            current_path = Path(current)
            for name in names:
                path = current_path / name
                metadata = path.lstat()
                if _is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    raise AdmissionError(label + ":linklike_or_special")
                _validate_artifact_parent_chain(
                    environment_root, path, root_record,
                    label + ":directory_invalid")
                relative = path.relative_to(physical_root).as_posix()
                directory_reports[relative] = {
                    "resolved_path": str(path.resolve(strict=True)),
                    "filesystem_identity": _node_report(metadata),
                }
            for name in filenames:
                path = current_path / name
                metadata = path.lstat()
                if (_is_linklike(metadata)
                        or not stat.S_ISREG(metadata.st_mode)
                        or int(metadata.st_nlink) != 1):
                    raise AdmissionError(label + ":linklike_or_special")
                files.add(path.relative_to(physical_root).as_posix())
        root_after = physical_root.lstat()
        if _snapshot(root_before) != _snapshot(root_after):
            raise AdmissionError(label + ":changed_during_scan")
        for relative, before in directory_reports.items():
            path = physical_root / PurePosixPath(relative)
            after = path.lstat()
            if (_is_linklike(after) or not stat.S_ISDIR(after.st_mode)
                    or _node_report(after) != before["filesystem_identity"]):
                raise AdmissionError(label + ":changed_during_scan")
    except AdmissionError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise AdmissionError(label + ":scan_unavailable") from error
    return (
        physical_root,
        {
            "resolved_path": str(physical_root.resolve(strict=True)),
            "filesystem_identity": _node_report(root_after),
        },
        {key: directory_reports[key] for key in sorted(directory_reports)},
        sorted(files),
    )


def _host_customization_inventory(
        noetic_root: Path, system_root: Path) -> Mapping[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for role, root in (("noetic", noetic_root), ("system", system_root)):
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise AdmissionError(
                "runtime_import_customization_scan_unavailable:" + role
            ) from error
        for path in children:
            if (path.name not in {"sitecustomize.py", "usercustomize.py"}
                    and path.suffix != ".pth"):
                continue
            try:
                metadata = path.lstat()
            except OSError as error:
                raise AdmissionError(
                    "runtime_import_customization_scan_unavailable:" + role
                ) from error
            if _is_linklike(metadata) or not stat.S_ISREG(metadata.st_mode):
                raise AdmissionError(
                    "runtime_import_customization_artifact_invalid:" + role)
            raw = path.read_bytes()
            result[role + ":" + path.name] = {
                "path": str(path.resolve(strict=True)),
                "size_bytes": len(raw),
                "sha256": _sha256(raw),
            }
    return result


def _expected_runtime_import_ids(
        module_specs: Mapping[str, Any], package_trees: Mapping[str, Any],
        python_root_inventories: Mapping[str, Any],
        customization_inventory: Mapping[str, Any],
        aux_executable_closure: Mapping[str, Any]) -> List[str]:
    tree_ids = [
        "tree:" + tree_id + ":" + relative
        for tree_id in sorted(package_trees)
        for relative in sorted(package_trees[tree_id]["files"])
    ]
    root_ids = []
    for role in sorted(python_root_inventories):
        inventory = python_root_inventories[role]
        root_ids.append("python-root:" + role)
        root_ids.extend(
            "python-root-directory:" + role + ":" + relative
            for relative in sorted(inventory["directories"]))
        root_ids.extend(
            "python-root-file:" + role + ":" + relative
            for relative in sorted(inventory["files"]))
    return (
        ["executable", "probe_source", "python_entry"]
        + root_ids
        + tree_ids
        + ["module:" + name for name in sorted(module_specs)]
        + [
            "customization:" + name
            for name in sorted(customization_inventory)]
        + ["aux:" + name for name in sorted(aux_executable_closure)]
        + ["asset:" + role for role in RUNTIME_IMPORT_ASSET_ROLES]
    )


def _pure_is_relative_to(path: PurePosixPath, root: PurePosixPath) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_runtime_import_authority(
        authority: Mapping[str, Any], environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]],
        roslaunch: Mapping[str, Any], astra: Mapping[str, Any],
        probe_source_identity: Mapping[str, Any]) -> Tuple[
            Mapping[str, Any], Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    value = authority.get("runtime_import_probe")
    if not isinstance(value, Mapping) or set(value) != RUNTIME_IMPORT_PROBE_KEYS:
        raise AdmissionError("runtime_import_probe_authority_schema_invalid")
    if (not _valid_identity(value.get("probe_source_identity"))
            or dict(value["probe_source_identity"])
            != dict(probe_source_identity)):
        raise AdmissionError("runtime_import_probe_source_anchor_mismatch")

    # Classify Python startup customizations before the complete root
    # inventory check.  The exact inventory below would also reject these
    # files, but keeping this host-owned, purpose-specific gate makes the
    # production failure unambiguous and preserves the stronger invariant
    # that ``-S`` is only a supplement: no site/user customization or ``.pth``
    # artifact may exist anywhere on the two exposed import-root surfaces.
    customization = value.get("customization_inventory")
    if not isinstance(customization, Mapping) or customization:
        raise AdmissionError(
            "runtime_import_probe_customization_inventory_not_empty")
    noetic_python_root = _rooted(environment_root, PYTHONPATH_ENTRIES[0])
    system_python_root = _rooted(environment_root, PYTHONPATH_ENTRIES[1])
    if _host_customization_inventory(noetic_python_root, system_python_root):
        raise AdmissionError(
            "runtime_import_probe_undeclared_customization_artifact")

    module_specs = value.get("module_specs")
    logical_modules = authority["roslaunch"]["module_closure"]
    if (not isinstance(module_specs, Mapping)
            or set(module_specs) != set(logical_modules)):
        raise AdmissionError("runtime_import_probe_module_set_invalid")
    physical_modules: Dict[str, Mapping[str, Any]] = {}
    stable_module_specs: Dict[str, Mapping[str, Any]] = {}
    for name in sorted(module_specs):
        spec = module_specs[name]
        if (not isinstance(spec, Mapping) or set(spec) != MODULE_SPEC_KEYS
                or spec.get("loader_kind") != "SourceFileLoader"
                or (spec.get("expected_version") is not None
                    and (not isinstance(spec["expected_version"], str)
                         or not spec["expected_version"]))
                or dict(spec.get("identity", {}))
                != dict(logical_modules[name])):
            raise AdmissionError(
                "runtime_import_probe_module_spec_invalid:" + name)
        physical_modules[name] = {
            "identity": _identity_view(
                roslaunch["module_closure"][name], physical=True),
            "loader_kind": spec["loader_kind"],
            "expected_version": spec["expected_version"],
        }
        stable_module_specs[name] = {
            "identity": dict(spec["identity"]),
            "loader_kind": spec["loader_kind"],
            "expected_version": spec["expected_version"],
        }

    root_inventory_specs = value.get("python_root_inventories")
    expected_python_roots = {
        "noetic": PYTHONPATH_ENTRIES[0],
        "system": PYTHONPATH_ENTRIES[1],
    }
    if (not isinstance(root_inventory_specs, Mapping)
            or set(root_inventory_specs) != set(expected_python_roots)):
        raise AdmissionError(
            "runtime_import_probe_python_root_inventory_schema_invalid")
    physical_root_inventories: Dict[str, Mapping[str, Any]] = {}
    stable_root_inventories: Dict[str, Mapping[str, Any]] = {}
    host_root_inventory_material: Dict[str, Mapping[str, Any]] = {}
    root_inventory_physical_paths = set()
    for role in ("noetic", "system"):
        inventory = root_inventory_specs[role]
        expected_root = expected_python_roots[role]
        if (not isinstance(inventory, Mapping)
                or set(inventory) != PYTHON_ROOT_INVENTORY_KEYS
                or inventory.get("root_path") != expected_root
                or type(inventory.get("directories")) is not list
                or inventory["directories"] != sorted(inventory["directories"])
                or len(inventory["directories"])
                != len(set(inventory["directories"]))
                or any(not _safe_tree_relative(item)
                       for item in inventory["directories"])
                or not isinstance(inventory.get("files"), Mapping)
                or not inventory["files"]
                or any(
                    not _safe_tree_relative(relative)
                    or not _valid_identity(identity)
                    for relative, identity in inventory["files"].items())):
            raise AdmissionError(
                "runtime_import_probe_python_root_inventory_schema_invalid:"
                + role)
        (physical_root, root_provenance, directory_provenance,
         actual_files) = _enumerate_exact_python_root(
            role=role, logical_root=expected_root,
            environment_root=environment_root, roots=roots)
        if list(directory_provenance) != inventory["directories"]:
            raise AdmissionError(
                "runtime_import_probe_python_root_directory_set_mismatch:"
                + role)
        if set(actual_files) != set(inventory["files"]):
            raise AdmissionError(
                "runtime_import_probe_python_root_file_set_mismatch:" + role)
        physical_files: Dict[str, Mapping[str, Any]] = {}
        stable_files: Dict[str, Mapping[str, Any]] = {}
        host_files: Dict[str, Mapping[str, Any]] = {}
        for relative in actual_files:
            expected_path = (
                PurePosixPath(expected_root) / PurePosixPath(relative)
            ).as_posix()
            record, unused_raw, unused_path = _validate_file(
                inventory["files"][relative], environment_root, roots,
                "runtime_import_python_root:" + role + ":" + relative,
                expected_path=expected_path)
            if record["resolved_path"] in root_inventory_physical_paths:
                raise AdmissionError(
                    "runtime_import_probe_python_root_file_reused")
            root_inventory_physical_paths.add(record["resolved_path"])
            physical_files[relative] = _identity_view(record, physical=True)
            stable_files[relative] = _identity_view(record, physical=False)
            host_files[relative] = dict(record)
        physical_root_inventories[role] = {
            "root_path": str(physical_root),
            "directories": list(inventory["directories"]),
            "files": physical_files,
        }
        stable_root_inventories[role] = {
            "root_path": expected_root,
            "directories": list(inventory["directories"]),
            "files": stable_files,
        }
        host_root_inventory_material[role] = {
            "root": root_provenance,
            "directories": directory_provenance,
            "files": host_files,
        }

    tree_specs = value.get("package_trees")
    if (not isinstance(tree_specs, Mapping)
            or set(tree_specs) != set(RUNTIME_IMPORT_REQUIRED_TREE_FILES)):
        raise AdmissionError("runtime_import_probe_package_tree_set_invalid")
    physical_trees: Dict[str, Mapping[str, Any]] = {}
    stable_trees: Dict[str, Mapping[str, Any]] = {}
    flattened_physical_files = set()
    for tree_id in sorted(tree_specs):
        tree = tree_specs[tree_id]
        expected_root = PurePosixPath(MODULE_PATHS[tree_id]).parent.as_posix()
        if (not isinstance(tree, Mapping) or set(tree) != PACKAGE_TREE_KEYS
                or tree.get("root_path") != expected_root
                or not isinstance(tree.get("files"), Mapping)
                or not tree["files"]
                or not RUNTIME_IMPORT_REQUIRED_TREE_FILES[tree_id].issubset(
                    set(tree["files"]))
                or any(
                    not _safe_tree_relative(relative)
                    or not _valid_identity(identity)
                    for relative, identity in tree["files"].items())):
            raise AdmissionError(
                "runtime_import_probe_package_tree_schema_invalid:" + tree_id)
        physical_root, unused_directories, actual_files = _enumerate_package_tree(
            logical_root=expected_root, environment_root=environment_root,
            roots=roots, label=tree_id)
        if set(actual_files) != set(tree["files"]):
            raise AdmissionError(
                "runtime_import_probe_package_tree_file_set_mismatch:" + tree_id)
        root_record = _root_for_logical(expected_root, roots)
        physical_files: Dict[str, Mapping[str, Any]] = {}
        stable_files: Dict[str, Mapping[str, Any]] = {}
        for relative in sorted(actual_files):
            expected_path = (
                PurePosixPath(expected_root) / PurePosixPath(relative)).as_posix()
            record, unused_raw, unused_path = _validate_file(
                tree["files"][relative], environment_root, roots,
                "runtime_import_package_tree:" + tree_id + ":" + relative,
                expected_path=expected_path)
            if record["resolved_path"] in flattened_physical_files:
                raise AdmissionError(
                    "runtime_import_probe_package_tree_file_reused")
            flattened_physical_files.add(record["resolved_path"])
            physical_files[relative] = _identity_view(record, physical=True)
            stable_files[relative] = _identity_view(record, physical=False)
        physical_trees[tree_id] = {
            "root_path": str(physical_root), "files": physical_files}
        stable_trees[tree_id] = {
            "root_path": expected_root, "files": stable_files}
        if not root_record.get("immutable_execution"):
            raise AdmissionError(
                "runtime_import_probe_package_tree_root_not_immutable:" + tree_id)

    for tree_id, tree in stable_trees.items():
        tree_root = PurePosixPath(tree["root_path"])
        matching_roles = [
            role for role, inventory in stable_root_inventories.items()
            if _pure_is_relative_to(
                tree_root, PurePosixPath(inventory["root_path"]))]
        if len(matching_roles) != 1:
            raise AdmissionError(
                "runtime_import_probe_package_tree_root_inventory_mismatch:"
                + tree_id)
        role = matching_roles[0]
        python_root = PurePosixPath(
            stable_root_inventories[role]["root_path"])
        for relative, identity in tree["files"].items():
            root_relative = (
                tree_root / PurePosixPath(relative)
            ).relative_to(python_root).as_posix()
            if (stable_root_inventories[role]["files"].get(root_relative)
                    != identity):
                raise AdmissionError(
                    "runtime_import_probe_package_tree_root_inventory_mismatch:"
                    + tree_id + ":" + relative)

    for name, spec in physical_modules.items():
        if spec["identity"]["path"] not in flattened_physical_files:
            raise AdmissionError(
                "runtime_import_probe_module_not_in_package_tree:" + name)
        if spec["identity"]["path"] not in root_inventory_physical_paths:
            raise AdmissionError(
                "runtime_import_probe_module_not_in_python_root_inventory:"
                + name)

    # Re-scan after every root/package/module identity has been reopened.  An
    # attacker cannot add a startup customization between the early policy
    # classification and construction of the isolated-probe request.
    actual_customization = _host_customization_inventory(
        noetic_python_root, system_python_root)
    if actual_customization:
        raise AdmissionError(
            "runtime_import_probe_undeclared_customization_artifact")

    auxiliary = value.get("aux_executable_closure")
    if (not isinstance(auxiliary, Mapping)
            or set(auxiliary) != {"roslaunch"}
            or dict(auxiliary["roslaunch"])
            != dict(authority["roslaunch"]["executable"])):
        raise AdmissionError("runtime_import_probe_aux_closure_invalid")
    physical_auxiliary = {
        "roslaunch": _identity_view(roslaunch["executable"], physical=True)}
    stable_auxiliary = {
        "roslaunch": _identity_view(roslaunch["executable"], physical=False)}

    physical_assets = {
        "package_xml": _identity_view(astra["package_xml"], physical=True),
        "launch": _identity_view(astra["launch"], physical=True),
        "node_executable": _identity_view(
            astra["resolved_node_executable"], physical=True),
    }
    physical_spec = {
        "executable_identity": _identity_view(
            roslaunch["python_executable_target"], physical=True),
        "probe_source_identity": dict(probe_source_identity),
        "noetic_python_root": noetic_python_root,
        "system_python_root": system_python_root,
        "vendor_install_prefix": _rooted(environment_root, VENDOR_PREFIX),
        "module_closure": physical_modules,
        "package_trees": physical_trees,
        "python_root_inventories": physical_root_inventories,
        "python_root_host_provenance": host_root_inventory_material,
        "customization_inventory": {},
        "aux_executable_closure": physical_auxiliary,
        "python_entry_path": _rooted(environment_root, PYTHON_ENTRY_PATH),
        "python_entry_link_text": PYTHON_ENTRY_LINK_TEXT,
        "astra_package_root": _rooted(environment_root, ASTRA_PACKAGE_ROOT),
        "astra_assets": physical_assets,
    }
    stable = {
        "probe_source_identity": dict(probe_source_identity),
        "module_specs": stable_module_specs,
        "package_trees": stable_trees,
        "python_root_inventories": stable_root_inventories,
        "customization_inventory": {},
        "aux_executable_closure": stable_auxiliary,
    }
    trusted_python_roots = [
        {
            "role": "noetic", "path": PYTHONPATH_ENTRIES[0],
            "owner_uid": roots["noetic"]["expected_owner_uid"],
            "inventory_manifest_sha256": _sha256(_json_bytes(
                stable_root_inventories["noetic"])),
            "inventory_physical_sha256": _sha256(_json_bytes(
                host_root_inventory_material["noetic"])),
            "directory_count": len(
                stable_root_inventories["noetic"]["directories"]),
            "file_count": len(stable_root_inventories["noetic"]["files"]),
            "package_tree_ids": sorted(
                name for name in stable_trees
                if _pure_is_relative_to(
                    PurePosixPath(stable_trees[name]["root_path"]),
                    PurePosixPath(PYTHONPATH_ENTRIES[0]))),
        },
        {
            "role": "system", "path": PYTHONPATH_ENTRIES[1],
            "owner_uid": roots["system"]["expected_owner_uid"],
            "inventory_manifest_sha256": _sha256(_json_bytes(
                stable_root_inventories["system"])),
            "inventory_physical_sha256": _sha256(_json_bytes(
                host_root_inventory_material["system"])),
            "directory_count": len(
                stable_root_inventories["system"]["directories"]),
            "file_count": len(stable_root_inventories["system"]["files"]),
            "package_tree_ids": sorted(
                name for name in stable_trees
                if _pure_is_relative_to(
                    PurePosixPath(stable_trees[name]["root_path"]),
                    PurePosixPath(PYTHONPATH_ENTRIES[1]))),
        },
    ]
    return stable, physical_spec, trusted_python_roots


def _provenance_identity(value: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    identity = {key: value.get(key) for key in IDENTITY_KEYS}
    return identity if _valid_identity(identity) else None


def _identity_matches_provenance(
        provenance: Any, expected: Mapping[str, Any]) -> bool:
    identity = _provenance_identity(provenance)
    return identity is not None and dict(identity) == dict(expected)


def _validate_runtime_import_probe_report(
        report: Any, *, admission_mode: str,
        physical_spec: Mapping[str, Any], stable_authority: Mapping[str, Any]
        ) -> Mapping[str, Any]:
    if (not isinstance(report, Mapping)
            or set(report) != RUNTIME_IMPORT_PROBE_REPORT_KEYS):
        raise AdmissionError("runtime_import_probe_report_schema_invalid")
    production = admission_mode == PRODUCTION_MODE
    expected_probe_mode = (
        "production_camera_runtime_import" if production
        else "test_only_validator_fixture")
    expected_ids = _expected_runtime_import_ids(
        physical_spec["module_closure"], physical_spec["package_trees"],
        physical_spec["python_root_inventories"],
        physical_spec["customization_inventory"],
        physical_spec["aux_executable_closure"])
    scalar_expectations = {
        "schema_version": 1,
        "gate_id": "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1",
        "admission_mode": expected_probe_mode,
        "read_only": True,
        "starts_ros_graph": False,
        "opens_camera": False,
        "runs_inference": False,
        "authorizes_motion": False,
        "publishes_ros_messages": False,
        "algorithm_validated": True,
        "validator_unit_test_pass": not production,
        "validated_pass": production,
        "runtime_import_probe_pass": production,
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
        "parent_environment_restored": True,
        "failures": [],
        "expected_ids": expected_ids,
        "executed_ids": expected_ids,
    }
    for key, expected in scalar_expectations.items():
        if report.get(key) != expected:
            if key == "failures" and isinstance(report.get(key), list):
                first = next(
                    (value for value in report[key]
                     if isinstance(value, str) and value), None)
                if first is not None:
                    raise AdmissionError(
                        "runtime_import_probe_failed:" + first)
            raise AdmissionError(
                "runtime_import_probe_report_semantic_invalid:" + key)
    if len(expected_ids) != len(set(expected_ids)):
        raise AdmissionError("runtime_import_probe_expected_ids_not_unique")

    argv = report.get("argv")
    request_identity = report.get("request_identity")
    if (not isinstance(argv, list) or len(argv) != 7
            or argv[:6] != [
                physical_spec["executable_identity"]["path"],
                "-I", "-S", "-B",
                physical_spec["probe_source_identity"]["path"],
                "--child-request"]
            or not isinstance(argv[6], str) or not Path(argv[6]).is_absolute()
            or not _valid_identity(request_identity)
            or request_identity["path"] != argv[6]):
        raise AdmissionError("runtime_import_probe_argv_invalid")

    child = report.get("child_marker")
    if not isinstance(child, Mapping) or set(child) != RUNTIME_IMPORT_CHILD_KEYS:
        raise AdmissionError("runtime_import_probe_child_schema_invalid")
    child_scalars = {
        "schema_version": 1,
        "marker": "LIMO_ROS1_CAMERA_RUNTIME_IMPORT_CHILD_V1",
        "status": "PASS",
        "exit_code": 0,
        "test_only": not production,
        "algorithm_validated": True,
        "validator_unit_test_pass": not production,
        "validated_pass": production,
        "runtime_import_probe_pass": production,
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
        "expected_ids": expected_ids,
        "executed_ids": expected_ids,
        "loaded_nonstdlib_module_ids": sorted(
            physical_spec["module_closure"]),
        "forbidden_environment_keys_present": [],
        "isolation": {
            "isolated": True, "no_site": True,
            "dont_write_bytecode": True},
        "sitecustomize_loaded": False,
        "failures": [],
    }
    for key, expected in child_scalars.items():
        if child.get(key) != expected:
            raise AdmissionError(
                "runtime_import_probe_child_semantic_invalid:" + key)
    if (not isinstance(child.get("request_id"), str)
            or re.fullmatch(r"[0-9a-f]{64}", child["request_id"]) is None
            or child.get("request_sha256") != request_identity["sha256"]):
        raise AdmissionError("runtime_import_probe_child_request_invalid")

    if (not _identity_matches_provenance(
            child.get("executable_provenance"),
            physical_spec["executable_identity"])
            or not _identity_matches_provenance(
                child.get("probe_source_provenance"),
                physical_spec["probe_source_identity"])):
        raise AdmissionError("runtime_import_probe_child_core_identity_invalid")
    module_provenance = child.get("module_provenance")
    module_versions = child.get("module_versions")
    module_loaders = child.get("module_loaders")
    if (not isinstance(module_provenance, Mapping)
            or set(module_provenance) != set(physical_spec["module_closure"])
            or not isinstance(module_versions, Mapping)
            or set(module_versions) != set(physical_spec["module_closure"])
            or not isinstance(module_loaders, Mapping)
            or set(module_loaders) != set(physical_spec["module_closure"])):
        raise AdmissionError("runtime_import_probe_child_module_schema_invalid")
    for name, spec in physical_spec["module_closure"].items():
        if (not _identity_matches_provenance(
                    module_provenance[name], spec["identity"])
                or module_versions[name] != spec["expected_version"]
                or module_loaders[name] != spec["loader_kind"]):
            raise AdmissionError(
                "runtime_import_probe_child_module_invalid:" + name)

    expected_tree_provenance = {
        tree_id + ":" + relative: identity
        for tree_id, tree in physical_spec["package_trees"].items()
        for relative, identity in tree["files"].items()
    }
    actual_tree_provenance = child.get("package_tree_file_provenance")
    if (not isinstance(actual_tree_provenance, Mapping)
            or set(actual_tree_provenance) != set(expected_tree_provenance)
            or any(
                not _identity_matches_provenance(
                    actual_tree_provenance[key], expected)
                for key, expected in expected_tree_provenance.items())):
        raise AdmissionError("runtime_import_probe_child_tree_invalid")
    expected_root_directories: Dict[str, Mapping[str, Any]] = {}
    expected_root_files: Dict[str, Mapping[str, Any]] = {}
    for role, material in physical_spec["python_root_host_provenance"].items():
        root = material["root"]
        expected_root_directories[role + ":."] = {
            "path": root["resolved_path"],
            **dict(root["filesystem_identity"]),
        }
        for relative, directory in material["directories"].items():
            expected_root_directories[role + ":" + relative] = {
                "path": directory["resolved_path"],
                **dict(directory["filesystem_identity"]),
            }
        for relative, record in material["files"].items():
            filesystem = record["filesystem_identity"]
            expected_root_files[role + ":" + relative] = {
                "path": record["resolved_path"],
                "size_bytes": record["size_bytes"],
                "sha256": record["sha256"],
                "device": filesystem["device"],
                "inode": filesystem["inode"],
                "mode": filesystem["mode"],
                "nlink": filesystem["nlink"],
                "mtime_ns": filesystem["mtime_ns"],
            }
    if child.get("python_root_directory_provenance") != expected_root_directories:
        raise AdmissionError(
            "runtime_import_probe_child_python_root_directory_invalid")
    if child.get("python_root_file_provenance") != expected_root_files:
        raise AdmissionError(
            "runtime_import_probe_child_python_root_file_invalid")
    for field, expected in (
            ("customization_provenance", {}),
            ("aux_executable_provenance",
             physical_spec["aux_executable_closure"]),
            ("astra_asset_provenance", physical_spec["astra_assets"])):
        actual = child.get(field)
        if (not isinstance(actual, Mapping) or set(actual) != set(expected)
                or any(
                    not _identity_matches_provenance(actual[key], identity)
                    for key, identity in expected.items())):
            raise AdmissionError(
                "runtime_import_probe_child_provenance_invalid:" + field)
    environment_keys = child.get("child_environment_keys")
    if (not isinstance(environment_keys, list)
            or len(environment_keys) != len(set(environment_keys))
            or any(not isinstance(key, str) for key in environment_keys)
            or any(
                key in {
                    "PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH",
                    "LD_PRELOAD", "CMAKE_PREFIX_PATH", "ROS_PACKAGE_PATH"}
                or key.startswith(("ROS_", "LD_", "CATKIN_", "COLCON_", "AMENT_"))
                for key in environment_keys)):
        raise AdmissionError("runtime_import_probe_child_environment_invalid")

    stable = {
        **stable_authority,
        "probe_gate_id": "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1",
        "probe_admission_mode": expected_probe_mode,
        "expected_ids": expected_ids,
        "executed_ids": list(report["executed_ids"]),
        "parent_environment_restored": True,
        "isolation": dict(child["isolation"]),
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
    }
    return stable


def _run_runtime_import_probe(
        probe_module: Any, physical_spec: Mapping[str, Any],
        stable_authority: Mapping[str, Any], *, production: bool,
        evaluator: Optional[Any], subprocess_runner: Optional[Any]
        ) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    if production:
        if evaluator is not None or subprocess_runner is not None:
            raise AdmissionError(
                "production_runtime_import_probe_test_seam_forbidden")
        report = probe_module.run_camera_runtime_import_probe(
            admission_mode=probe_module.PRODUCTION_MODE)
        admission_mode = PRODUCTION_MODE
    else:
        selected = (
            probe_module.run_camera_runtime_import_probe
            if evaluator is None else evaluator)
        if not callable(selected):
            raise AdmissionError("test_runtime_import_probe_evaluator_invalid")
        kwargs = {
            key: value for key, value in physical_spec.items()
            if key != "python_root_host_provenance"}
        kwargs["admission_mode"] = probe_module.TEST_ONLY_MODE
        if subprocess_runner is not None:
            kwargs["subprocess_runner"] = subprocess_runner
        report = selected(**kwargs)
        admission_mode = TEST_ONLY_MODE
    stable = _validate_runtime_import_probe_report(
        report, admission_mode=admission_mode,
        physical_spec=physical_spec, stable_authority=stable_authority)
    return dict(report), stable


def _xml_root(raw: bytes, code: str) -> ET.Element:
    try:
        text = raw.decode("utf-8", errors="strict")
        lowered = text.lower()
        if "<!doctype" in lowered or "<!entity" in lowered:
            raise AdmissionError(code)
        return ET.fromstring(text)
    except AdmissionError:
        raise
    except (UnicodeError, ET.ParseError) as error:
        raise AdmissionError(code) from error


def _validate_astra(
        authority: Mapping[str, Any], environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    value = authority.get("astra_camera")
    if (not isinstance(value, Mapping) or set(value) != ASTRA_KEYS
            or value.get("package_root") != ASTRA_PACKAGE_ROOT):
        raise AdmissionError("astra_schema_invalid")
    package, package_raw, unused_package_path = _validate_file(
        value["package_xml"], environment_root, roots, "astra_package_xml",
        expected_path=ASTRA_PACKAGE_XML)
    launch, launch_raw, unused_launch_path = _validate_file(
        value["launch"], environment_root, roots, "astra_launch",
        expected_path=ASTRA_LAUNCH_PATH)
    node, unused_node_raw, unused_node_path = _validate_file(
        value["node_executable"], environment_root, roots,
        "astra_node_executable", executable=True, expected_path=ASTRA_NODE_PATH)
    package_root = _xml_root(package_raw, "astra_package_xml_invalid")
    direct_names = [
        child for child in list(package_root) if child.tag == "name"]
    if (package_root.tag != "package" or len(direct_names) != 1
            or not isinstance(direct_names[0].text, str)
            or direct_names[0].text.strip() != "astra_camera"):
        raise AdmissionError("astra_package_identity_invalid")
    if (launch["size_bytes"] != DABAI_REFERENCE_SIZE_BYTES
            or launch["sha256"] != DABAI_REFERENCE_SHA256):
        raise AdmissionError("astra_launch_reference_identity_mismatch")
    launch_root = _xml_root(launch_raw, "astra_launch_xml_invalid")
    nodes = list(launch_root.iter("node"))
    if (launch_root.tag != "launch" or len(nodes) != 1
            or nodes[0].get("pkg") != "astra_camera"
            or nodes[0].get("type") != "astra_camera_node"):
        raise AdmissionError("astra_launch_resolution_invalid")
    if PurePosixPath(node["path"]).name != nodes[0].get("type"):
        raise AdmissionError("astra_node_resolution_mismatch")
    return {
        "package_name": "astra_camera",
        "launch_node_type": "astra_camera_node",
        "package_root": ASTRA_PACKAGE_ROOT,
        "package_xml": package,
        "launch": launch,
        "resolved_node_executable": node,
    }


def _validate_environment_directory(
        logical: str, environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]], label: str) -> Mapping[str, Any]:
    root_record = _root_for_logical(logical, roots)
    path = _rooted(environment_root, logical)
    chain = _validate_artifact_parent_chain(
        environment_root, path, root_record,
        "exec_environment_directory_invalid:" + label)
    return {"path": logical, "resolved_path": str(path), "chain": chain}


def _validate_state_directory(
        logical: str, environment_root: Path,
        state_root: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    report = _validate_environment_directory(
        logical, environment_root, {"state": state_root}, label)
    path = _rooted(environment_root, logical)
    metadata = path.lstat()
    expected_owner = int(state_root["declaration"]["owner_uid"])
    if (_owner(metadata) != expected_owner
            or int(metadata.st_mode) & 0o700 != 0o700):
        raise AdmissionError(
            "exec_environment_state_directory_owner_mode_invalid:" + label)
    return report


def _validate_master_uri(value: Any) -> str:
    if value != ROS_MASTER_URI:
        raise AdmissionError("exec_environment_master_uri_invalid")
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port != 11371 or parsed.username is not None
            or parsed.password is not None or parsed.path != "/"
            or parsed.query or parsed.fragment):
        raise AdmissionError("exec_environment_master_uri_invalid")
    return value


def _clean_environment(
        authority: Mapping[str, Any], environment_root: Path,
        roots: Mapping[str, Mapping[str, Any]]) -> Tuple[
            Mapping[str, str], Mapping[str, Any]]:
    forbidden_ambient = sorted(
        key for key in os.environ
        if (key in FORBIDDEN_AMBIENT_KEYS or key.startswith("ROS_")
            or key.startswith("LD_")))
    if forbidden_ambient:
        raise AdmissionError(
            "exec_environment_ambient_forbidden:" + forbidden_ambient[0])
    value = authority.get("exec_environment")
    if not isinstance(value, Mapping) or set(value) != EXEC_ENV_KEYS:
        raise AdmissionError("exec_environment_schema_invalid")
    if (value.get("policy_id") != EXEC_ENV_POLICY_ID
            or value.get("path_entries") != list(PATH_ENTRIES)
            or value.get("pythonpath_entries") != list(PYTHONPATH_ENTRIES)
            or value.get("ros_package_path_entries")
            != list(ROS_PACKAGE_PATH_ENTRIES)
            or value.get("ld_library_path_entries")
            != list(LD_LIBRARY_PATH_ENTRIES)
            or value.get("cmake_prefix_path_entries")
            != list(CMAKE_PREFIX_PATH_ENTRIES)
            or not _valid_sha256(value.get("expected_environment_sha256"))):
        raise AdmissionError("exec_environment_policy_invalid")
    master_uri = _validate_master_uri(value.get("ros_master_uri"))
    state_root = _logical_absolute(
        value.get("state_root"), "exec_environment_state_root_invalid")
    expected_state_prefix = STATE_PREFIX + "/" + authority["admission_id"]
    if state_root != expected_state_prefix:
        raise AdmissionError("exec_environment_state_root_invalid")

    directory_reports = {}
    for group, entries in (
            ("path", PATH_ENTRIES), ("pythonpath", PYTHONPATH_ENTRIES),
            ("ros_package_path", ROS_PACKAGE_PATH_ENTRIES),
            ("ld_library_path", LD_LIBRARY_PATH_ENTRIES),
            ("cmake_prefix_path", CMAKE_PREFIX_PATH_ENTRIES),
            ("ros_etc_dir", (NOETIC_PREFIX + "/etc/ros",)),
            ("ros_root", (NOETIC_PREFIX + "/share/ros",))):
        if len(entries) != len(set(entries)):
            raise AdmissionError("exec_environment_duplicate_path:" + group)
        directory_reports[group] = [
            _validate_environment_directory(
                item, environment_root, roots, group + ":" + str(index))
            for index, item in enumerate(entries)]

    state_reports = {}
    state = roots["state"]
    state_reports["state_root"] = _validate_state_directory(
        state_root, environment_root, state, "state_root")
    for name in STATE_SUBDIRECTORIES:
        state_reports[name] = _validate_state_directory(
            state_root + "/" + name, environment_root, state, name)

    environment = {
        "CMAKE_PREFIX_PATH": ":".join(CMAKE_PREFIX_PATH_ENTRIES),
        "HOME": state_root + "/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LD_LIBRARY_PATH": ":".join(LD_LIBRARY_PATH_ENTRIES),
        "PATH": ":".join(PATH_ENTRIES),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": ":".join(PYTHONPATH_ENTRIES),
        "ROS_DISTRO": "noetic",
        "ROS_ETC_DIR": NOETIC_PREFIX + "/etc/ros",
        "ROS_HOME": state_root + "/ros-home",
        "ROS_IP": "127.0.0.1",
        "ROS_LOG_DIR": state_root + "/log",
        "ROS_MASTER_URI": master_uri,
        "ROS_PACKAGE_PATH": ":".join(ROS_PACKAGE_PATH_ENTRIES),
        "ROS_PYTHON_VERSION": "3",
        "ROS_ROOT": NOETIC_PREFIX + "/share/ros",
        "ROS_VERSION": "1",
        "TMPDIR": state_root + "/tmp",
    }
    digest = _sha256(_json_bytes(environment))
    if digest != value["expected_environment_sha256"]:
        raise AdmissionError("exec_environment_sha256_mismatch")
    if ("PYTHONHOME" in environment or "LD_PRELOAD" in environment
            or "ROS_HOSTNAME" in environment):
        raise AdmissionError("exec_environment_forbidden_key")
    return environment, {
        "policy_id": EXEC_ENV_POLICY_ID,
        "environment_sha256": digest,
        "key_set": sorted(environment),
        "directory_reports": directory_reports,
        "state_reports": state_reports,
        "ambient_environment_copied": False,
        "environment_derived_from_empty_mapping": True,
        "ambient_path_ignored": "PATH" in os.environ,
        "ambient_sensitive_keys_observed": sorted(
            key for key in SENSITIVE_AMBIENT_KEYS if key in os.environ),
    }


def _runtime_execution_identity(
        authority: Mapping[str, Any], *, production: bool) -> Mapping[str, Any]:
    if not hasattr(os, "getuid") or not hasattr(os, "geteuid"):
        if production:
            raise AdmissionError("production_runtime_identity_unavailable")
        uid = euid = 0
    else:
        uid = int(os.getuid())
        euid = int(os.geteuid())
    if production and (uid != euid or euid == 0):
        raise AdmissionError("production_runtime_execution_identity_invalid")
    state = next(
        (item for item in authority.get("trusted_install_roots", [])
         if isinstance(item, Mapping) and item.get("role") == "state"), None)
    state_owner = state.get("owner_uid") if isinstance(state, Mapping) else None
    if type(state_owner) is not int or state_owner != uid:
        raise AdmissionError("runtime_state_owner_uid_mismatch")
    return {
        "uid": uid,
        "euid": euid,
        "state_owner_uid": state_owner,
        "requires_non_root": True,
    }


def _stable_execution_closure_material(
        *, authority: Mapping[str, Any],
        authority_identity: Mapping[str, Any],
        trusted_roots: Mapping[str, Any],
        roslaunch: Mapping[str, Any], astra: Mapping[str, Any],
        clean_environment: Mapping[str, str],
        environment_report: Mapping[str, Any],
        trusted_python_roots: Sequence[Mapping[str, Any]],
        runtime_probe_material: Mapping[str, Any],
        runtime_identity: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "authority_identity": dict(authority_identity),
        "trusted_install_roots": dict(trusted_roots),
        "roslaunch_admission": dict(roslaunch),
        "astra_resolution": dict(astra),
        "clean_exec_environment": dict(clean_environment),
        "clean_exec_environment_report": dict(environment_report),
        "trusted_system_python_roots": [
            item["path"] for item in trusted_python_roots],
        "trusted_system_python_root_provenance": [
            dict(item) for item in trusted_python_roots],
        "runtime_import_probe_stable_material": dict(runtime_probe_material),
        "runtime_execution_identity": dict(runtime_identity),
    }


def evaluate_camera_runtime_install_admission(
        authority_path: Optional[Path] = None,
        authority_expected_identity: Optional[Mapping[str, Any]] = None,
        *, environment_root: Path = Path("/"),
        _test_owner_uid: Optional[int] = None,
        _before_final_revalidation_hook: Optional[Any] = None,
        _runtime_import_probe_evaluator: Optional[Any] = None,
        _runtime_import_probe_subprocess_runner: Optional[Any] = None
        ) -> Mapping[str, Any]:
    """Recompute the host-selected camera runtime install without running ROS.

    Production callers must use the default authority arguments.  The only
    explicit authority seam is underscored by ``_test_owner_uid`` and accepts
    a non-root filesystem containing an authority whose ``test_only`` field is
    true.  Consequently a caller cannot pair arbitrary bytes with a matching
    hash and promote them into a production runtime admission.
    """
    failures: List[str] = []
    authority: Mapping[str, Any] = {}
    authority_identity = None
    authority_path_policy = None
    selected_expected_identity = None
    selected_authority_path = None
    trusted_roots: Mapping[str, Any] = {}
    roslaunch = None
    astra = None
    clean_environment: Mapping[str, str] = {}
    environment_report = None
    runtime_import_probe_report = None
    runtime_import_probe_stable_material = None
    trusted_system_python_roots = None
    runtime_execution_identity = None
    execution_closure_material = None
    execution_closure_digest = None
    runtime_import_probe_validated = False
    resolved_environment = None
    requested_test_mode = _test_owner_uid is not None
    production_anchor_bound = (
        isinstance(PRODUCTION_AUTHORITY_PATH, str)
        and bool(PRODUCTION_AUTHORITY_PATH)
        and type(PRODUCTION_AUTHORITY_SIZE_BYTES) is int
        and PRODUCTION_AUTHORITY_SIZE_BYTES >= 0
        and _valid_sha256(PRODUCTION_AUTHORITY_SHA256))
    try:
        environment_argument = Path(environment_root)
        try:
            environment_metadata = environment_argument.lstat()
        except OSError as error:
            raise AdmissionError("environment_root_unavailable") from error
        if (_is_linklike(environment_metadata)
                or not stat.S_ISDIR(environment_metadata.st_mode)):
            raise AdmissionError("environment_root_linklike_or_not_directory")
        environment = environment_argument.resolve(strict=True)
        resolved_environment = environment
        system_environment_root = Path("/").resolve(strict=True)
        if requested_test_mode:
            if (type(_test_owner_uid) is not int or _test_owner_uid < 0
                    or authority_path is None
                    or authority_expected_identity is None
                    or environment == system_environment_root):
                raise AdmissionError("test_owner_seam_policy_invalid")
            selected_authority_path = Path(authority_path)
            selected_expected_identity = authority_expected_identity
        else:
            if _before_final_revalidation_hook is not None:
                raise AdmissionError("production_test_hook_forbidden")
            if (_runtime_import_probe_evaluator is not None
                    or _runtime_import_probe_subprocess_runner is not None):
                raise AdmissionError(
                    "production_runtime_import_probe_test_seam_forbidden")
            if authority_path is not None or authority_expected_identity is not None:
                raise AdmissionError("production_authority_override_forbidden")
            if environment != system_environment_root:
                raise AdmissionError("production_environment_root_mismatch")
            if not production_anchor_bound:
                raise AdmissionError(
                    "camera_runtime_install_authority_anchor_unavailable")
            if os.name != "posix" or not sys.platform.startswith("linux"):
                raise AdmissionError("production_linux_posix_required")
            selected_authority_path = Path(str(PRODUCTION_AUTHORITY_PATH))
            selected_expected_identity = {
                "path": str(PRODUCTION_AUTHORITY_PATH),
                "size_bytes": PRODUCTION_AUTHORITY_SIZE_BYTES,
                "sha256": PRODUCTION_AUTHORITY_SHA256,
            }
        authority_path_policy = _validate_authority_path_policy(
            selected_authority_path,
            environment if requested_test_mode else system_environment_root,
            (0, _test_owner_uid) if requested_test_mode else (0,))
        authority, authority_identity = _load_authority(
            selected_authority_path, selected_expected_identity)
        if requested_test_mode:
            if authority.get("test_only") is not True:
                raise AdmissionError("test_owner_seam_policy_invalid")
        elif authority.get("test_only") is True:
            raise AdmissionError("production_authority_test_only")
        runtime_execution_identity = _runtime_execution_identity(
            authority, production=not requested_test_mode)
        roots, trusted_roots = _validate_root_declarations(
            authority, environment, _test_owner_uid)
        roslaunch = _validate_roslaunch(authority, environment, roots)
        astra = _validate_astra(authority, environment, roots)
        clean_environment, environment_report = _clean_environment(
            authority, environment, roots)
        probe_module, probe_source_identity = _load_exact_runtime_import_probe(
            production=not requested_test_mode)
        runtime_authority, physical_probe_spec, trusted_system_python_roots = (
            _validate_runtime_import_authority(
                authority, environment, roots, roslaunch, astra,
                probe_source_identity))
        runtime_import_probe_report, runtime_import_probe_stable_material = (
            _run_runtime_import_probe(
                probe_module, physical_probe_spec, runtime_authority,
                production=not requested_test_mode,
                evaluator=_runtime_import_probe_evaluator,
                subprocess_runner=_runtime_import_probe_subprocess_runner))
        runtime_import_probe_validated = True
        if _before_final_revalidation_hook is not None:
            if not callable(_before_final_revalidation_hook):
                raise AdmissionError("test_final_hook_invalid")
            _before_final_revalidation_hook()
        # Reopen the authority and every child/root after the complete first
        # pass.  This does not authorize execution (the atomic launcher must
        # perform its own descriptor-bound checks), but it prevents a fixture
        # or admission report from hiding a replacement between individual
        # reads and the final result.
        try:
            final_authority, final_authority_identity = _load_authority(
                selected_authority_path, selected_expected_identity)
        except AdmissionError as error:
            raise AdmissionError(
                "authority_changed_during_validation") from error
        if (final_authority_identity != authority_identity
                or final_authority != authority):
            raise AdmissionError("authority_changed_during_validation")
        if (_validate_authority_path_policy(
                selected_authority_path,
                environment if requested_test_mode
                else system_environment_root,
                (0, _test_owner_uid) if requested_test_mode else (0,))
                != authority_path_policy):
            raise AdmissionError("authority_path_policy_changed")
        final_runtime_execution_identity = _runtime_execution_identity(
            final_authority, production=not requested_test_mode)
        final_roots, final_trusted_roots = _validate_root_declarations(
            final_authority, environment, _test_owner_uid)
        final_roslaunch = _validate_roslaunch(
            final_authority, environment, final_roots)
        final_astra = _validate_astra(
            final_authority, environment, final_roots)
        final_environment, final_environment_report = _clean_environment(
            final_authority, environment, final_roots)
        final_probe_module, final_probe_source_identity = (
            _load_exact_runtime_import_probe(
                production=not requested_test_mode))
        final_runtime_authority, final_physical_probe_spec, final_python_roots = (
            _validate_runtime_import_authority(
                final_authority, environment, final_roots,
                final_roslaunch, final_astra, final_probe_source_identity))
        final_probe_report, final_probe_stable_material = (
            _run_runtime_import_probe(
                final_probe_module, final_physical_probe_spec,
                final_runtime_authority,
                production=not requested_test_mode,
                evaluator=_runtime_import_probe_evaluator,
                subprocess_runner=_runtime_import_probe_subprocess_runner))
        if (final_trusted_roots != trusted_roots
                or final_roslaunch != roslaunch
                or final_astra != astra
                or final_environment != clean_environment
                or final_environment_report != environment_report
                or final_runtime_execution_identity
                != runtime_execution_identity
                or final_probe_source_identity != probe_source_identity
                or final_runtime_authority != runtime_authority
                or final_physical_probe_spec != physical_probe_spec
                or final_python_roots != trusted_system_python_roots
                or final_probe_stable_material
                != runtime_import_probe_stable_material):
            raise AdmissionError("install_closure_changed_during_validation")
        runtime_import_probe_report = final_probe_report
        execution_closure_material = _stable_execution_closure_material(
            authority=final_authority,
            authority_identity=final_authority_identity,
            trusted_roots=final_trusted_roots,
            roslaunch=final_roslaunch, astra=final_astra,
            clean_environment=final_environment,
            environment_report=final_environment_report,
            trusted_python_roots=final_python_roots,
            runtime_probe_material=final_probe_stable_material,
            runtime_identity=final_runtime_execution_identity)
        execution_closure_digest = _sha256(
            _json_bytes(execution_closure_material))
    except AdmissionError as error:
        failures.append(error.code)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append("camera_runtime_admission_unexpected:" + type(error).__name__)

    algorithm_validated = not failures
    test_only = authority.get("test_only") is True
    production_validated = (
        algorithm_validated and not requested_test_mode and not test_only
        and production_anchor_bound and runtime_import_probe_validated)
    probe_argv = (
        list(runtime_import_probe_report.get("argv", []))
        if isinstance(runtime_import_probe_report, Mapping) else [])
    isolated_child_started = bool(
        probe_argv and _runtime_import_probe_evaluator is None)
    trusted_python_root_paths = (
        [item["path"] for item in trusted_system_python_roots]
        if isinstance(trusted_system_python_roots, Sequence) else None)
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "marker": CLI_MARKER.rstrip(),
        "scope": SCOPE,
        "mode": TEST_ONLY_MODE if requested_test_mode else PRODUCTION_MODE,
        "admission_mode": (
            TEST_ONLY_MODE if requested_test_mode else PRODUCTION_MODE),
        "test_only": requested_test_mode,
        "read_only": True,
        "runs_external_commands": isolated_child_started,
        "runs_isolated_python_subprocess": isolated_child_started,
        "runtime_import_probe_argv": probe_argv,
        "starts_ros_graph": False,
        "starts_camera": False,
        "publishes_ros_messages": False,
        "authorizes_motion": False,
        "authorizes_camera_launch": False,
        "authorizes_field_delivery": False,
        "accepted_by_formal_field_evidence_consumer": False,
        "formal_acceptance": False,
        "delivery_ready": False,
        "algorithm_validated": algorithm_validated,
        "validator_unit_test_pass": (
            algorithm_validated and requested_test_mode and test_only),
        "validated_pass": production_validated,
        "camera_runtime_install_pass": production_validated,
        "runtime_import_smoke_required": True,
        "runtime_import_smoke_validated": production_validated,
        "runtime_import_probe_pass": production_validated,
        "production_authority_anchor_bound": production_anchor_bound,
        "authority_selection": {
            "selection_mode": (
                "test_only_explicit_anchor" if requested_test_mode
                else "host_fixed_production_anchor"),
            "selected_path": (
                str(selected_authority_path)
                if selected_authority_path is not None else None),
            "expected_identity": (
                dict(selected_expected_identity)
                if isinstance(selected_expected_identity, Mapping) else None),
        },
        "authority_id": authority.get("admission_id"),
        "authority_identity": authority_identity,
        "authority_path_policy": authority_path_policy,
        "environment_root": (
            str(resolved_environment)
            if resolved_environment is not None else None),
        "trusted_install_roots": trusted_roots,
        "roslaunch_admission": roslaunch,
        "astra_resolution": astra,
        "clean_exec_environment": dict(clean_environment),
        "clean_exec_environment_report": environment_report,
        "trusted_system_python_roots": trusted_python_root_paths,
        "trusted_system_python_root_provenance": trusted_system_python_roots,
        "runtime_import_probe_report": runtime_import_probe_report,
        "runtime_import_probe_stable_material": (
            runtime_import_probe_stable_material),
        "runtime_execution_identity": runtime_execution_identity,
        "execution_closure_material": execution_closure_material,
        "execution_closure_digest": execution_closure_digest,
        "failures": sorted(set(failures)),
    }


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Statically validate one externally anchored ROS1/Noetic camera "
            "runtime installation; never starts ROS or a camera."))
    return parser.parse_args(args)


def main(args: Optional[Sequence[str]] = None) -> int:
    parse_args(args)
    result = evaluate_camera_runtime_install_admission()
    sys.stdout.buffer.write(CLI_MARKER.encode("ascii") + _json_bytes(result))
    sys.stdout.buffer.write(b"\n")
    return 0 if result["validated_pass"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
