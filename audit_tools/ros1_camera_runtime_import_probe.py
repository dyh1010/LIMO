"""Isolated ROS1/Noetic camera-runtime import probe.

The production entry point is deliberately fail closed until a release binds a
host-owned immutable production specification.  The private test-only path is
useful for proving the probe algorithm, but its result can never authorize a
runtime install, field evidence, a ROS launch, or delivery.

The parent reopens every declared artifact, starts the exact versioned Python
target with ``-I -S -B`` and a newly constructed environment, and accepts one
strict JSON marker only.  The child imports the declared ROS/Python closure,
checks each module's ``__file__`` and ``__spec__.origin``, checks the installed
Astra package artifacts by exact path, and never imports a camera node or
starts/contacts a ROS graph.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
GATE_ID = "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1"
REQUEST_MARKER = "LIMO_ROS1_CAMERA_RUNTIME_IMPORT_REQUEST_V1"
CHILD_MARKER = "LIMO_ROS1_CAMERA_RUNTIME_IMPORT_CHILD_V1"
PRODUCTION_SPEC_MARKER = "LIMO_ROS1_CAMERA_RUNTIME_IMPORT_SPEC_V1"
CLI_MARKER = "ROS1_CAMERA_RUNTIME_IMPORT_PROBE "
TEST_ONLY_MODE = "test_only_validator_fixture"
PRODUCTION_MODE = "production_camera_runtime_import"

REQUIRED_MODULES = (
    "catkin_pkg",
    "rosgraph",
    "roslaunch",
    "roslib",
    "rospkg",
    "yaml",
)
ASSET_ROLES = ("package_xml", "launch", "node_executable")
AUX_EXECUTABLE_ROLES = ("roslaunch",)

# A later generation may bind one external immutable production specification.
# The spec deliberately omits the probe source identity: the parent derives it
# from the exact executing source bytes, preventing a self-authentication loop.
PRODUCTION_SPEC_PATH: Optional[str] = None
PRODUCTION_SPEC_SIZE_BYTES: Optional[int] = None
PRODUCTION_SPEC_SHA256: Optional[str] = None
PRODUCTION_SPEC_TRUST_ROOT: Optional[str] = None
PRODUCTION_SPEC_OWNER_UID = 0

_IDENTITY_KEYS = {"path", "size_bytes", "sha256"}
_MODULE_SPEC_KEYS = {"identity", "loader_kind", "expected_version"}
_TREE_SPEC_KEYS = {"root_path", "files"}
_ROOT_INVENTORY_SPEC_KEYS = {"root_path", "directories", "files"}
_PROVENANCE_KEYS = {
    "path", "size_bytes", "sha256", "device", "inode", "mode", "nlink",
    "mtime_ns",
}
_REQUEST_KEYS = {
    "schema_version", "marker", "request_id", "admission_mode", "test_only",
    "executable_identity", "probe_source_identity", "noetic_python_root",
    "system_python_root", "vendor_install_prefix", "module_closure",
    "package_trees", "python_root_inventories", "customization_inventory",
    "aux_executable_closure",
    "python_entry_path", "python_entry_link_text",
    "astra_package_root", "astra_assets", "expected_ids",
}
_CHILD_KEYS = {
    "schema_version", "marker", "request_id", "request_sha256", "status",
    "exit_code", "test_only", "algorithm_validated",
    "validator_unit_test_pass", "validated_pass",
    "runtime_import_probe_pass", "formal_consumer",
    "field_evidence_admitted", "delivery_ready", "expected_ids",
    "executed_ids", "executable_provenance", "probe_source_provenance",
    "module_provenance", "module_versions", "module_loaders",
    "package_tree_file_provenance", "customization_provenance",
    "python_root_directory_provenance", "python_root_file_provenance",
    "aux_executable_provenance",
    "astra_asset_provenance", "loaded_nonstdlib_module_ids",
    "child_environment_keys", "forbidden_environment_keys_present",
    "isolation", "sitecustomize_loaded", "failures",
}
_ISOLATION_KEYS = {"isolated", "no_site", "dont_write_bytecode"}
_PRODUCTION_SPEC_KEYS = {
    "schema_version", "marker", "executable_identity",
    "noetic_python_root", "system_python_root", "vendor_install_prefix",
    "module_closure", "package_trees", "python_root_inventories",
    "customization_inventory",
    "aux_executable_closure", "python_entry_path", "python_entry_link_text",
    "astra_package_root", "astra_assets",
}
_FORBIDDEN_ENVIRONMENT_EXACT = {
    "PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LD_PRELOAD",
    "CMAKE_PREFIX_PATH", "ROS_PACKAGE_PATH",
}
_FORBIDDEN_ENVIRONMENT_PREFIXES = (
    "ROS_", "LD_", "CATKIN_", "COLCON_", "AMENT_",
)
_CHILD_ENVIRONMENT_ALLOWLIST = {
    "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "TEMP", "TMP",
    "TMPDIR", "WINDIR",
}
_FORBIDDEN_PATH_COMPONENTS = {"src", "source", "devel", "build"}
_MODULE_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


class ProbeError(RuntimeError):
    """Stable fail-closed probe error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("nonfinite_json_number:" + value)


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and value == value.lower()
        and all(character in "0123456789abcdef" for character in value))


def _valid_identity(value: Any) -> bool:
    return (
        isinstance(value, Mapping) and set(value) == _IDENTITY_KEYS
        and isinstance(value.get("path"), str)
        and Path(value["path"]).is_absolute()
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] >= 0 and _valid_sha256(value.get("sha256")))


def _identity(provenance: Mapping[str, Any]) -> Mapping[str, Any]:
    return {key: provenance[key] for key in sorted(_IDENTITY_KEYS)}


def _is_linklike(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(metadata, "st_file_attributes", 0) & flag)


def _immutable_execution_mode_safe(
        metadata: os.stat_result, expected_owner_uid: int) -> bool:
    """Allow root owner-write only when the executing identity is non-root."""
    effective_uid = int(os.geteuid()) if hasattr(os, "geteuid") else 0
    forbidden = (
        0o022 if int(expected_owner_uid) == 0 and effective_uid != 0
        else 0o222)
    return (int(metadata.st_mode) & forbidden) == 0


def _attest_production_execution_identity() -> None:
    if not hasattr(os, "getuid") or not hasattr(os, "geteuid"):
        raise ProbeError("probe_production_execution_identity_unavailable")
    if int(os.getuid()) != int(os.geteuid()) or int(os.geteuid()) == 0:
        raise ProbeError("probe_production_execution_identity_invalid")


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(str(Path(path))))


def _path_chain(path: Path) -> Sequence[Path]:
    absolute = _absolute_lexical(path)
    return tuple(reversed(absolute.parents)) + (absolute,)


def _forbidden_path_component(path: Path) -> bool:
    return any(
        part.lower() in _FORBIDDEN_PATH_COMPONENTS for part in Path(path).parts)


def _directory(path: Path, code: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or _forbidden_path_component(candidate):
        raise ProbeError(code)
    try:
        for item in _path_chain(candidate):
            metadata = os.lstat(str(item))
            if _is_linklike(metadata):
                raise ProbeError(code)
        resolved = candidate.resolve(strict=True)
        metadata = os.lstat(str(resolved))
    except ProbeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError(code) from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProbeError(code)
    return resolved


def _metadata_snapshot(metadata: os.stat_result) -> Tuple[int, ...]:
    return (
        int(getattr(metadata, "st_dev", 0)),
        int(getattr(metadata, "st_ino", 0)),
        int(metadata.st_mode),
        int(getattr(metadata, "st_nlink", 1)),
        int(metadata.st_size),
        int(getattr(metadata, "st_mtime_ns", 0)),
    )


def _directory_provenance(path: Path, code: str) -> Mapping[str, Any]:
    resolved = _directory(path, code)
    try:
        before = os.lstat(str(resolved))
        if _is_linklike(before) or not stat.S_ISDIR(before.st_mode):
            raise ProbeError(code)
        after = os.lstat(str(resolved))
    except ProbeError:
        raise
    except OSError as error:
        raise ProbeError(code) from error
    if _metadata_snapshot(before) != _metadata_snapshot(after):
        raise ProbeError(code + ":changed")
    return {
        "path": str(resolved),
        "device": int(getattr(after, "st_dev", 0)),
        "inode": int(getattr(after, "st_ino", 0)),
        "mode": int(after.st_mode),
        "owner_uid": int(getattr(after, "st_uid", 0)),
        "group_gid": int(getattr(after, "st_gid", 0)),
        "nlink": int(getattr(after, "st_nlink", 1)),
        "size_bytes": int(after.st_size),
        "mtime_ns": int(getattr(after, "st_mtime_ns", 0)),
    }


def _file_provenance(path: Path, code: str, *, executable: bool = False) -> Mapping[str, Any]:
    candidate = Path(path)
    if not candidate.is_absolute() or _forbidden_path_component(candidate):
        raise ProbeError(code)
    try:
        for item in _path_chain(candidate):
            metadata = os.lstat(str(item))
            if _is_linklike(metadata):
                raise ProbeError(code + ":linklike")
        resolved = candidate.resolve(strict=True)
        metadata = os.lstat(str(resolved))
    except ProbeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError(code + ":missing") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ProbeError(code + ":not_regular")
    if int(getattr(metadata, "st_nlink", 1)) != 1:
        raise ProbeError(code + ":hardlink")
    if executable and os.name != "nt" and not (
            metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        raise ProbeError(code + ":not_executable")
    sha256 = _sha256_file(resolved)
    try:
        after = os.lstat(str(resolved))
    except OSError as error:
        raise ProbeError(code + ":changed") from error
    if _metadata_snapshot(metadata) != _metadata_snapshot(after):
        raise ProbeError(code + ":changed")
    return {
        "path": str(resolved),
        "size_bytes": int(after.st_size),
        "sha256": sha256,
        "device": int(getattr(after, "st_dev", 0)),
        "inode": int(getattr(after, "st_ino", 0)),
        "mode": int(after.st_mode),
        "nlink": int(getattr(after, "st_nlink", 1)),
        "mtime_ns": int(getattr(after, "st_mtime_ns", 0)),
    }


def _reopen_identity(
        expected: Any, code: str, *, executable: bool = False) -> Mapping[str, Any]:
    if not _valid_identity(expected):
        raise ProbeError(code + ":anchor_invalid")
    actual = _file_provenance(
        Path(expected["path"]), code, executable=executable)
    if _identity(actual) != dict(expected):
        raise ProbeError(code + ":identity_mismatch")
    return actual


def _production_spec_anchor_bound() -> bool:
    return (
        isinstance(PRODUCTION_SPEC_PATH, str) and bool(PRODUCTION_SPEC_PATH)
        and Path(PRODUCTION_SPEC_PATH).is_absolute()
        and isinstance(PRODUCTION_SPEC_TRUST_ROOT, str)
        and bool(PRODUCTION_SPEC_TRUST_ROOT)
        and Path(PRODUCTION_SPEC_TRUST_ROOT).is_absolute()
        and type(PRODUCTION_SPEC_SIZE_BYTES) is int
        and PRODUCTION_SPEC_SIZE_BYTES >= 0
        and _valid_sha256(PRODUCTION_SPEC_SHA256))


def _validate_readonly_owner_chain(
        trusted_root: Path, target: Path, expected_owner_uid: int,
        *, target_is_directory: bool = False) -> None:
    root = _absolute_lexical(trusted_root)
    candidate = _absolute_lexical(target)
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ProbeError("probe_production_spec_outside_trust_root") from error
    chain = [root]
    current = root
    for part in relative.parts:
        current = current / part
        chain.append(current)
    try:
        for index, item in enumerate(chain):
            metadata = os.lstat(str(item))
            is_target = index == len(chain) - 1
            if (
                _is_linklike(metadata)
                or int(getattr(metadata, "st_uid", 0)) != expected_owner_uid
                or not _immutable_execution_mode_safe(
                    metadata, expected_owner_uid)
                or (
                    is_target
                    and ((target_is_directory
                          and not stat.S_ISDIR(metadata.st_mode))
                         or (not target_is_directory
                             and (not stat.S_ISREG(metadata.st_mode)
                                  or int(getattr(metadata, "st_nlink", 1)) != 1))))
                or (not is_target and not stat.S_ISDIR(metadata.st_mode))
            ):
                raise ProbeError("probe_production_spec_file_policy_invalid")
    except ProbeError:
        raise
    except OSError as error:
        raise ProbeError("probe_production_spec_file_policy_invalid") from error


def _load_external_production_spec(
        path: Path, expected_size: int, expected_sha256: str,
        trusted_chain_root: Path, expected_owner_uid: int,
        probe_source_identity: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_readonly_owner_chain(
        trusted_chain_root, path, expected_owner_uid)
    expected = {
        "path": str(Path(path)), "size_bytes": expected_size,
        "sha256": expected_sha256}
    provenance = _reopen_identity(expected, "probe_production_spec")
    try:
        payload = _strict_json_bytes(Path(provenance["path"]).read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise ProbeError("probe_production_spec_strict_json_invalid") from error
    if not isinstance(payload, Mapping) or set(payload) != _PRODUCTION_SPEC_KEYS:
        raise ProbeError("probe_production_spec_schema_invalid")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("marker") != PRODUCTION_SPEC_MARKER
    ):
        raise ProbeError("probe_production_spec_policy_invalid")
    _validate_readonly_owner_chain(
        trusted_chain_root, path, expected_owner_uid)
    if _file_provenance(path, "probe_production_spec") != provenance:
        raise ProbeError("probe_production_spec_changed_during_read")
    result = {
        key: value for key, value in payload.items()
        if key not in {"schema_version", "marker"}
    }
    result["probe_source_identity"] = dict(probe_source_identity)
    return result


def _attest_production_parent() -> None:
    _attest_production_execution_identity()
    if (
        not sys.flags.isolated or not sys.flags.no_site
        or not sys.dont_write_bytecode
    ):
        raise ProbeError("probe_production_parent_flags_invalid")
    if "sitecustomize" in sys.modules or "usercustomize" in sys.modules:
        raise ProbeError("probe_production_parent_customization_loaded")
    trusted_finders = {
        importlib.machinery.BuiltinImporter,
        importlib.machinery.FrozenImporter,
        importlib.machinery.PathFinder,
    }
    if any(finder not in trusted_finders for finder in sys.meta_path):
        raise ProbeError("probe_production_parent_meta_path_untrusted")
    interpreter_root = Path(sys.base_prefix).resolve(strict=True)
    for name, module in (("json", json), ("hashlib", hashlib), ("stat", stat)):
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        loader_name = type(getattr(spec, "loader", None)).__name__
        if origin in {"built-in", "frozen"}:
            if loader_name not in {"BuiltinImporter", "FrozenImporter", "type"}:
                raise ProbeError(
                    "probe_production_parent_stdlib_identity_invalid:" + name)
            continue
        if not isinstance(origin, str) or loader_name != "SourceFileLoader":
            raise ProbeError(
                "probe_production_parent_stdlib_identity_invalid:" + name)
        try:
            path = Path(origin).resolve(strict=True)
            path.relative_to(interpreter_root)
            metadata = os.lstat(str(path))
        except (OSError, RuntimeError, ValueError) as error:
            raise ProbeError(
                "probe_production_parent_stdlib_identity_invalid:" + name
            ) from error
        if (
            int(metadata.st_mode) & 0o170000 != 0o100000
            or int(getattr(metadata, "st_nlink", 1)) != 1
        ):
            raise ProbeError(
                "probe_production_parent_stdlib_identity_invalid:" + name)
        try:
            _validate_readonly_owner_chain(interpreter_root, path, 0)
        except ProbeError as error:
            raise ProbeError(
                "probe_production_parent_stdlib_identity_invalid:" + name
            ) from error


def _validate_python_entry(
        entry_value: Any, link_text: Any,
        executable_provenance: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(entry_value, str) or not Path(entry_value).is_absolute():
        raise ProbeError("probe_python_entry_invalid")
    entry = _absolute_lexical(Path(entry_value))
    try:
        for parent in reversed(entry.parents):
            metadata = os.lstat(str(parent))
            if _is_linklike(metadata):
                raise ProbeError("probe_python_entry_parent_linklike")
        metadata = os.lstat(str(entry))
        if _is_linklike(metadata):
            if not stat.S_ISLNK(metadata.st_mode) or not isinstance(link_text, str):
                raise ProbeError("probe_python_entry_link_invalid")
            observed = os.readlink(str(entry))
            if observed != link_text:
                raise ProbeError("probe_python_entry_link_text_mismatch")
            resolved = entry.resolve(strict=True)
        else:
            if link_text is not None or not stat.S_ISREG(metadata.st_mode):
                raise ProbeError("probe_python_entry_regular_invalid")
            resolved = entry.resolve(strict=True)
    except ProbeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError("probe_python_entry_unavailable") from error
    if resolved != Path(executable_provenance["path"]):
        raise ProbeError("probe_python_entry_target_mismatch")
    return {
        "entry_path": str(entry),
        "link_text": link_text,
        "resolved_target_path": str(resolved),
        "mode": int(metadata.st_mode),
        "device": int(getattr(metadata, "st_dev", 0)),
        "inode": int(getattr(metadata, "st_ino", 0)),
    }


def _is_under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve(strict=True).relative_to(Path(root).resolve(strict=True))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _ambient_forbidden_keys(environment: Mapping[str, str]) -> List[str]:
    return sorted(
        key for key in environment
        if key in _FORBIDDEN_ENVIRONMENT_EXACT
        or any(key.startswith(prefix) for prefix in _FORBIDDEN_ENVIRONMENT_PREFIXES))


def _clean_child_environment(environment: Mapping[str, str]) -> Mapping[str, str]:
    result = {
        key: value for key, value in environment.items()
        if key in _CHILD_ENVIRONMENT_ALLOWLIST
    }
    result.update({
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    })
    return result


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return (
        not path.is_absolute() and ".." not in path.parts
        and "." not in path.parts)


def _enumerate_regular_tree(root: Path, code: str) -> Mapping[str, Mapping[str, Any]]:
    tree_root = _directory(root, code + ":root")
    result: Dict[str, Mapping[str, Any]] = {}
    for current, directory_names, file_names in os.walk(str(tree_root), followlinks=False):
        current_path = Path(current)
        for name in sorted(directory_names):
            path = current_path / name
            try:
                metadata = os.lstat(str(path))
            except OSError as error:
                raise ProbeError(code + ":directory_missing") from error
            if _is_linklike(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise ProbeError(code + ":directory_linklike_or_invalid")
        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(tree_root).as_posix()
            result[relative] = _file_provenance(path, code + ":file:" + relative)
    return result


def _enumerate_exact_python_root(
        root: Path, code: str) -> Mapping[str, Any]:
    tree_root = _directory(root, code + ":root")
    root_before = _directory_provenance(tree_root, code + ":root")
    directories: Dict[str, Mapping[str, Any]] = {}
    files: Dict[str, Mapping[str, Any]] = {}
    try:
        for current, directory_names, file_names in os.walk(
                str(tree_root), followlinks=False):
            directory_names.sort()
            file_names.sort()
            current_path = Path(current)
            for name in directory_names:
                path = current_path / name
                relative = path.relative_to(tree_root).as_posix()
                directories[relative] = _directory_provenance(
                    path, code + ":directory:" + relative)
            for name in file_names:
                path = current_path / name
                relative = path.relative_to(tree_root).as_posix()
                files[relative] = _file_provenance(
                    path, code + ":file:" + relative)
    except ProbeError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError(code + ":scan_unavailable") from error
    root_after = _directory_provenance(tree_root, code + ":root")
    if root_after != root_before:
        raise ProbeError(code + ":changed_during_scan")
    for relative, before in directories.items():
        after = _directory_provenance(
            tree_root / Path(relative), code + ":directory:" + relative)
        if after != before:
            raise ProbeError(code + ":changed_during_scan:" + relative)
    return {
        "root_path": str(tree_root),
        "root_provenance": root_after,
        "directories": directories,
        "files": files,
    }


def _scan_customization_files(
        noetic_root: Path, system_root: Path
) -> Mapping[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for role, root in (("noetic", noetic_root), ("system", system_root)):
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if path.name not in {"sitecustomize.py", "usercustomize.py"} and path.suffix != ".pth":
                continue
            key = role + ":" + path.name
            result[key] = _file_provenance(
                path, "probe_customization_artifact:" + key)
    return result


def _enforce_customization_policy(
        inventory: Mapping[str, Any], *, production: bool) -> None:
    # ``-S`` proves these files were not executed, but cannot trace their
    # contents.  Production therefore requires an empty customization surface.
    if production and inventory:
        raise ProbeError("probe_production_customization_inventory_not_empty")


def _expected_ids(
        module_closure: Mapping[str, Any], astra_assets: Mapping[str, Any],
        package_trees: Mapping[str, Any],
        python_root_inventories: Mapping[str, Any],
        customization_inventory: Mapping[str, Any],
        aux_executable_closure: Mapping[str, Any],
) -> List[str]:
    tree_ids = []
    for tree_id in sorted(package_trees):
        for relative in sorted(package_trees[tree_id]["files"]):
            tree_ids.append("tree:" + tree_id + ":" + relative)
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
        + ["module:" + name for name in sorted(module_closure)]
        + ["customization:" + name for name in sorted(customization_inventory)]
        + ["aux:" + name for name in sorted(aux_executable_closure)]
        + ["asset:" + role for role in ASSET_ROLES if role in astra_assets]
    )


def _valid_module_spec(value: Any) -> bool:
    if (
        not isinstance(value, Mapping) or set(value) != _MODULE_SPEC_KEYS
        or not _valid_identity(value.get("identity"))
        or value.get("loader_kind") not in {
            "SourceFileLoader", "ExtensionFileLoader"}
        or (
            value.get("expected_version") is not None
            and (
                not isinstance(value.get("expected_version"), str)
                or not value["expected_version"]))
    ):
        return False
    filename = Path(value["identity"]["path"]).name
    if value["loader_kind"] == "SourceFileLoader":
        return filename.endswith(".py")
    return any(
        filename.endswith(suffix)
        for suffix in importlib.machinery.EXTENSION_SUFFIXES)


def _validate_python_root_inventories(
        value: Any, *, noetic_root: Path, system_root: Path,
        production: bool) -> Mapping[str, Mapping[str, Any]]:
    expected_roots = {"noetic": noetic_root, "system": system_root}
    if not isinstance(value, Mapping) or set(value) != set(expected_roots):
        raise ProbeError("probe_python_root_inventory_schema_invalid")
    result: Dict[str, Mapping[str, Any]] = {}
    seen_files = set()
    for role in ("noetic", "system"):
        spec = value[role]
        root = expected_roots[role]
        if (
            not isinstance(spec, Mapping)
            or set(spec) != _ROOT_INVENTORY_SPEC_KEYS
            or spec.get("root_path") != str(root)
            or type(spec.get("directories")) is not list
            or spec["directories"] != sorted(spec["directories"])
            or len(spec["directories"]) != len(set(spec["directories"]))
            or any(not _safe_relative_path(item) for item in spec["directories"])
            or not isinstance(spec.get("files"), Mapping)
            or not spec["files"]
            or any(
                not _safe_relative_path(relative)
                or not _valid_identity(identity)
                for relative, identity in spec["files"].items())
        ):
            raise ProbeError(
                "probe_python_root_inventory_schema_invalid:" + role)
        actual = _enumerate_exact_python_root(
            root, "probe_python_root_inventory:" + role)
        if sorted(actual["directories"]) != spec["directories"]:
            raise ProbeError(
                "probe_python_root_inventory_directory_set_mismatch:" + role)
        if set(actual["files"]) != set(spec["files"]):
            raise ProbeError(
                "probe_python_root_inventory_file_set_mismatch:" + role)
        for relative in sorted(actual["files"]):
            expected = spec["files"][relative]
            actual_file = actual["files"][relative]
            expected_path = (root / Path(relative)).resolve(strict=True)
            if (
                Path(expected["path"]) != expected_path
                or _identity(actual_file) != expected
                or actual_file["path"] in seen_files
            ):
                raise ProbeError(
                    "probe_python_root_inventory_file_identity_mismatch:"
                    + role + ":" + relative)
            seen_files.add(actual_file["path"])
        if production:
            _validate_readonly_owner_chain(
                Path("/"), root, 0, target_is_directory=True)
            for provenance in actual["directories"].values():
                _validate_readonly_owner_chain(
                    Path("/"), Path(provenance["path"]), 0,
                    target_is_directory=True)
            for provenance in actual["files"].values():
                _validate_readonly_owner_chain(
                    Path("/"), Path(provenance["path"]), 0)
        result[role] = actual
    return result


def _validate_inputs(spec: Mapping[str, Any], *, production: bool) -> Mapping[str, Any]:
    required = {
        "executable_identity", "probe_source_identity", "noetic_python_root",
        "system_python_root", "vendor_install_prefix", "module_closure",
        "package_trees", "python_root_inventories",
        "customization_inventory", "aux_executable_closure",
        "python_entry_path", "python_entry_link_text",
        "astra_package_root", "astra_assets",
    }
    if not isinstance(spec, Mapping) or set(spec) != required:
        raise ProbeError("probe_spec_schema_invalid")
    executable = _reopen_identity(
        spec["executable_identity"], "probe_executable", executable=True)
    if production and re.fullmatch(r"python3\.\d+", Path(executable["path"]).name) is None:
        raise ProbeError("probe_executable_not_versioned_target")
    python_entry = _validate_python_entry(
        spec["python_entry_path"], spec["python_entry_link_text"], executable)
    source = _reopen_identity(spec["probe_source_identity"], "probe_source")
    own_source = _file_provenance(Path(__file__), "probe_source")
    if _identity(source) != _identity(own_source):
        raise ProbeError("probe_source_not_exact_host_module")

    noetic_root = _directory(
        Path(spec["noetic_python_root"]), "probe_noetic_python_root_invalid")
    system_root = _directory(
        Path(spec["system_python_root"]), "probe_system_python_root_invalid")
    vendor_prefix = _directory(
        Path(spec["vendor_install_prefix"]), "probe_vendor_install_prefix_invalid")
    # The immutable production specification owns the vendor-prefix choice;
    # current deployment policy may use e.g. /opt/limo/ros1_camera_runtime.
    # A caller-controlled test fixture remains non-authoritative regardless of
    # its basename.
    if (
        noetic_root == system_root
        or noetic_root.name != "dist-packages"
        or noetic_root.parent.name != "python3"
        or noetic_root.parent.parent.name != "lib"
        or system_root.name != "dist-packages"
        or system_root.parent.name != "python3"
        or system_root.parent.parent.name != "lib"
    ):
        raise ProbeError("probe_install_root_layout_invalid")
    if production:
        for path in (noetic_root, system_root, vendor_prefix):
            _validate_readonly_owner_chain(
                Path("/"), path, 0, target_is_directory=True)
        for provenance in (executable, source):
            _validate_readonly_owner_chain(
                Path("/"), Path(provenance["path"]), 0)

    python_root_inventories = _validate_python_root_inventories(
        spec["python_root_inventories"], noetic_root=noetic_root,
        system_root=system_root, production=production)

    closure = spec["module_closure"]
    if (
        not isinstance(closure, Mapping)
        or not set(REQUIRED_MODULES).issubset(set(closure))
        or any(
            not isinstance(name, str) or _MODULE_NAME.fullmatch(name) is None
            or not _valid_module_spec(value)
            for name, value in closure.items())
    ):
        raise ProbeError("probe_module_closure_schema_invalid")
    module_provenance: Dict[str, Mapping[str, Any]] = {}
    seen_paths = set()
    for name in sorted(closure):
        actual = _reopen_identity(
            closure[name]["identity"], "probe_module_artifact:" + name)
        if (
            not (_is_under(Path(actual["path"]), noetic_root)
                 or _is_under(Path(actual["path"]), system_root))
            or actual["path"] in seen_paths
        ):
            raise ProbeError("probe_module_path_invalid:" + name)
        seen_paths.add(actual["path"])
        if production:
            _validate_readonly_owner_chain(
                Path("/"), Path(actual["path"]), 0)
        module_provenance[name] = actual

    tree_specs = spec["package_trees"]
    if (
        not isinstance(tree_specs, Mapping) or not tree_specs
        or any(
            not isinstance(tree_id, str)
            or _MODULE_NAME.fullmatch(tree_id) is None
            or not isinstance(tree_spec, Mapping)
            or set(tree_spec) != _TREE_SPEC_KEYS
            or not isinstance(tree_spec.get("root_path"), str)
            or not Path(tree_spec["root_path"]).is_absolute()
            or not isinstance(tree_spec.get("files"), Mapping)
            or not tree_spec["files"]
            or any(
                not _safe_relative_path(relative)
                or not _valid_identity(identity)
                for relative, identity in tree_spec["files"].items())
            for tree_id, tree_spec in tree_specs.items())
    ):
        raise ProbeError("probe_package_tree_schema_invalid")
    package_trees: Dict[str, Mapping[str, Any]] = {}
    tree_roots = set()
    manifest_paths = set()
    for tree_id in sorted(tree_specs):
        tree_spec = tree_specs[tree_id]
        tree_root = _directory(
            Path(tree_spec["root_path"]),
            "probe_package_tree_root_invalid:" + tree_id)
        if (
            not (_is_under(tree_root, noetic_root)
                 or _is_under(tree_root, system_root))
            or str(tree_root) in tree_roots
        ):
            raise ProbeError("probe_package_tree_root_invalid:" + tree_id)
        tree_roots.add(str(tree_root))
        if production:
            _validate_readonly_owner_chain(
                Path("/"), tree_root, 0, target_is_directory=True)
        actual_files = _enumerate_regular_tree(
            tree_root, "probe_package_tree:" + tree_id)
        if set(actual_files) != set(tree_spec["files"]):
            raise ProbeError("probe_package_tree_file_set_mismatch:" + tree_id)
        bound_files: Dict[str, Mapping[str, Any]] = {}
        for relative in sorted(actual_files):
            expected = tree_spec["files"][relative]
            actual = actual_files[relative]
            expected_path = (tree_root / Path(relative)).resolve(strict=True)
            if (
                Path(expected["path"]) != expected_path
                or _identity(actual) != expected
                or actual["path"] in manifest_paths
            ):
                raise ProbeError(
                    "probe_package_tree_identity_mismatch:" + tree_id + ":" + relative)
            manifest_paths.add(actual["path"])
            if production:
                _validate_readonly_owner_chain(
                    Path("/"), Path(actual["path"]), 0)
            bound_files[relative] = actual
        package_trees[tree_id] = {
            "root_path": str(tree_root), "files": bound_files}
    for name, provenance in module_provenance.items():
        if provenance["path"] not in manifest_paths:
            raise ProbeError("probe_module_not_in_package_tree:" + name)
        root_manifest_paths = {
            item["path"]
            for inventory in python_root_inventories.values()
            for item in inventory["files"].values()
        }
        if provenance["path"] not in root_manifest_paths:
            raise ProbeError("probe_module_not_in_python_root_inventory:" + name)

    customization = spec["customization_inventory"]
    if (
        not isinstance(customization, Mapping)
        or any(
            not isinstance(name, str) or not name
            or not _valid_identity(identity)
            for name, identity in customization.items())
    ):
        raise ProbeError("probe_customization_inventory_schema_invalid")
    actual_customization = _scan_customization_files(noetic_root, system_root)
    if set(actual_customization) != set(customization):
        raise ProbeError("probe_customization_inventory_set_mismatch")
    customization_provenance: Dict[str, Mapping[str, Any]] = {}
    for name in sorted(customization):
        if _identity(actual_customization[name]) != customization[name]:
            raise ProbeError("probe_customization_identity_mismatch:" + name)
        customization_provenance[name] = actual_customization[name]
    _enforce_customization_policy(
        customization_provenance, production=production)

    aux_closure = spec["aux_executable_closure"]
    if (
        not isinstance(aux_closure, Mapping)
        or set(aux_closure) != set(AUX_EXECUTABLE_ROLES)
        or any(
            not isinstance(name, str) or _MODULE_NAME.fullmatch(name) is None
            or not _valid_identity(identity)
            for name, identity in aux_closure.items())
    ):
        raise ProbeError("probe_aux_executable_closure_schema_invalid")
    aux_provenance: Dict[str, Mapping[str, Any]] = {}
    for name in sorted(aux_closure):
        actual = _reopen_identity(
            aux_closure[name], "probe_aux_executable:" + name,
            executable=True)
        if actual["path"] in manifest_paths:
            raise ProbeError("probe_aux_executable_path_reused:" + name)
        if production:
            _validate_readonly_owner_chain(
                Path("/"), Path(actual["path"]), 0)
        aux_provenance[name] = actual
    try:
        noetic_prefix = noetic_root.parents[2]
        expected_roslaunch = (noetic_prefix / "bin" / "roslaunch").resolve(strict=True)
    except (IndexError, OSError, RuntimeError, ValueError) as error:
        raise ProbeError("probe_noetic_prefix_layout_invalid") from error
    if Path(aux_provenance["roslaunch"]["path"]) != expected_roslaunch:
        raise ProbeError("probe_aux_roslaunch_path_mismatch")
    try:
        first_line = Path(aux_provenance["roslaunch"]["path"]).read_bytes().splitlines()[0]
        shebang = first_line.decode("ascii", errors="strict")
    except (IndexError, OSError, UnicodeError) as error:
        raise ProbeError("probe_aux_roslaunch_shebang_invalid") from error
    expected_shebang = "#!" + python_entry["entry_path"]
    if shebang != expected_shebang:
        # A test-only fixture maps the logical install root beneath a
        # temporary physical root.  It may therefore retain the production
        # logical shebang while the exact entry file lives below that fixture
        # root.  This compatibility is never accepted by production mode and
        # can never set runtime/formal/delivery PASS.
        logical_test_shebang = (
            not production and shebang.startswith("#!/")
            and python_entry["entry_path"].endswith(shebang[2:]))
        if not logical_test_shebang:
            raise ProbeError("probe_aux_roslaunch_shebang_mismatch")

    package_root = _directory(
        Path(spec["astra_package_root"]), "probe_astra_package_root_invalid")
    expected_package_root = vendor_prefix / "share" / "astra_camera"
    if package_root != expected_package_root.resolve(strict=True):
        raise ProbeError("probe_astra_package_root_mismatch")
    assets = spec["astra_assets"]
    if (
        not isinstance(assets, Mapping) or set(assets) != set(ASSET_ROLES)
        or any(not _valid_identity(value) for value in assets.values())
    ):
        raise ProbeError("probe_astra_assets_schema_invalid")
    expected_paths = {
        "package_xml": package_root / "package.xml",
        "launch": package_root / "launch" / "dabai_u3.launch",
        "node_executable": vendor_prefix / "lib" / "astra_camera" / "astra_camera_node",
    }
    asset_provenance: Dict[str, Mapping[str, Any]] = {}
    for role in ASSET_ROLES:
        actual = _reopen_identity(
            assets[role], "probe_astra_asset:" + role,
            executable=(role == "node_executable"))
        if Path(actual["path"]) != expected_paths[role].resolve(strict=True):
            raise ProbeError("probe_astra_asset_path_mismatch:" + role)
        if production:
            _validate_readonly_owner_chain(
                Path("/"), Path(actual["path"]), 0)
        asset_provenance[role] = actual

    return {
        "executable": executable,
        "python_entry": python_entry,
        "source": source,
        "noetic_root": noetic_root,
        "system_root": system_root,
        "vendor_prefix": vendor_prefix,
        "package_root": package_root,
        "modules": module_provenance,
        "module_specs": {
            name: {
                "identity": _identity(module_provenance[name]),
                "loader_kind": closure[name]["loader_kind"],
                "expected_version": closure[name]["expected_version"],
            }
            for name in sorted(closure)
        },
        "package_trees": package_trees,
        "python_root_inventories": python_root_inventories,
        "customization": customization_provenance,
        "aux_executables": aux_provenance,
        "assets": asset_provenance,
    }


def _request(
        spec: Mapping[str, Any], validated: Mapping[str, Any],
        admission_mode: str) -> Mapping[str, Any]:
    modules = {
        name: dict(value) for name, value in validated["module_specs"].items()}
    package_trees = {
        tree_id: {
            "root_path": tree["root_path"],
            "files": {
                relative: _identity(provenance)
                for relative, provenance in tree["files"].items()},
        }
        for tree_id, tree in validated["package_trees"].items()
    }
    python_root_inventories = {
        role: {
            "root_path": inventory["root_path"],
            "directories": sorted(inventory["directories"]),
            "files": {
                relative: _identity(provenance)
                for relative, provenance in inventory["files"].items()},
        }
        for role, inventory in validated["python_root_inventories"].items()
    }
    customization = {
        name: _identity(value)
        for name, value in validated["customization"].items()}
    aux_executables = {
        name: _identity(value)
        for name, value in validated["aux_executables"].items()}
    assets = {role: _identity(value) for role, value in validated["assets"].items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "marker": REQUEST_MARKER,
        "request_id": secrets.token_hex(32),
        "admission_mode": admission_mode,
        "test_only": admission_mode == TEST_ONLY_MODE,
        "executable_identity": _identity(validated["executable"]),
        "probe_source_identity": _identity(validated["source"]),
        "noetic_python_root": str(validated["noetic_root"]),
        "system_python_root": str(validated["system_root"]),
        "vendor_install_prefix": str(validated["vendor_prefix"]),
        "python_entry_path": validated["python_entry"]["entry_path"],
        "python_entry_link_text": validated["python_entry"]["link_text"],
        "module_closure": modules,
        "package_trees": package_trees,
        "python_root_inventories": python_root_inventories,
        "customization_inventory": customization,
        "aux_executable_closure": aux_executables,
        "astra_package_root": str(validated["package_root"]),
        "astra_assets": assets,
        "expected_ids": _expected_ids(
            modules, assets, package_trees, python_root_inventories,
            customization, aux_executables),
    }


def _trusted_stdlib_roots() -> Sequence[Path]:
    roots: List[Path] = []
    for name in ("stdlib", "platstdlib"):
        value = sysconfig.get_paths().get(name)
        if not value:
            continue
        try:
            root = Path(value).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _module_provenance(
        module: Any, root_set: Sequence[Path], name: str,
        expected_loader_kind: str) -> Mapping[str, Any]:
    path = getattr(module, "__file__", None)
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    loader = getattr(spec, "loader", None)
    if not isinstance(path, str) or not isinstance(origin, str):
        raise ProbeError("child_module_origin_invalid:" + name)
    path_provenance = _file_provenance(
        Path(path), "child_module_origin:" + name)
    origin_provenance = _file_provenance(
        Path(origin), "child_module_origin:" + name)
    if (
        _identity(path_provenance) != _identity(origin_provenance)
        or not any(_is_under(Path(path_provenance["path"]), root) for root in root_set)
        or type(loader).__name__ != expected_loader_kind
    ):
        raise ProbeError("child_module_origin_invalid:" + name)
    module_path = getattr(module, "__path__", None)
    if module_path is not None:
        values = [str(Path(item).resolve(strict=True)) for item in module_path]
        if values != [str(Path(path_provenance["path"]).parent)]:
            raise ProbeError("child_module_package_path_invalid:" + name)
    return path_provenance


def _loaded_nonstdlib_modules(
        roots: Sequence[Path], probe_path: Path) -> Sequence[str]:
    stdlib_roots = _trusted_stdlib_roots()
    names: List[str] = []
    for name, module in sorted(sys.modules.items()):
        path_value = getattr(module, "__file__", None)
        if not isinstance(path_value, str):
            continue
        try:
            path = Path(path_value).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise ProbeError("child_loaded_module_origin_invalid:" + name) from error
        if path == probe_path or any(_is_under(path, root) for root in stdlib_roots):
            continue
        if _forbidden_path_component(path):
            raise ProbeError("child_loaded_module_shadow_path:" + name)
        if not any(_is_under(path, root) for root in roots):
            raise ProbeError("child_loaded_module_outside_roots:" + name)
        names.append(name)
    return tuple(names)


def _empty_child_marker(failures: Sequence[str]) -> Mapping[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "marker": CHILD_MARKER,
        "request_id": None,
        "request_sha256": None,
        "status": "BLOCKED",
        "exit_code": 1,
        "test_only": True,
        "algorithm_validated": False,
        "validator_unit_test_pass": False,
        "validated_pass": False,
        "runtime_import_probe_pass": False,
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
        "expected_ids": [],
        "executed_ids": [],
        "executable_provenance": None,
        "probe_source_provenance": None,
        "module_provenance": {},
        "module_versions": {},
        "module_loaders": {},
        "package_tree_file_provenance": {},
        "python_root_directory_provenance": {},
        "python_root_file_provenance": {},
        "customization_provenance": {},
        "aux_executable_provenance": {},
        "astra_asset_provenance": {},
        "loaded_nonstdlib_module_ids": [],
        "child_environment_keys": sorted(os.environ),
        "forbidden_environment_keys_present": _ambient_forbidden_keys(os.environ),
        "isolation": {
            "isolated": bool(sys.flags.isolated),
            "no_site": bool(sys.flags.no_site),
            "dont_write_bytecode": bool(sys.dont_write_bytecode),
        },
        "sitecustomize_loaded": (
            "sitecustomize" in sys.modules or "usercustomize" in sys.modules),
        "failures": sorted(set(failures)),
    }


def _child_execute(request_path: Path) -> Tuple[Mapping[str, Any], int]:
    marker = _empty_child_marker([])
    failures: List[str] = []
    try:
        request_provenance = _file_provenance(
            Path(request_path), "child_request")
        raw = Path(request_path).read_bytes()
        request = _strict_json_bytes(raw)
        if not isinstance(request, Mapping) or set(request) != _REQUEST_KEYS:
            raise ProbeError("child_request_schema_invalid")
        if (
            request.get("schema_version") != SCHEMA_VERSION
            or request.get("marker") != REQUEST_MARKER
            or not isinstance(request.get("request_id"), str)
            or re.fullmatch(r"[0-9a-f]{64}", request["request_id"]) is None
            or request.get("admission_mode") not in {
                TEST_ONLY_MODE, PRODUCTION_MODE}
            or request.get("test_only")
            is not (request.get("admission_mode") == TEST_ONLY_MODE)
        ):
            raise ProbeError("child_request_policy_invalid")
        spec = {
            key: request[key] for key in (
                "executable_identity", "probe_source_identity",
                "noetic_python_root", "system_python_root",
                "vendor_install_prefix", "module_closure",
                "package_trees", "python_root_inventories",
                "customization_inventory",
                "aux_executable_closure",
                "python_entry_path", "python_entry_link_text",
                "astra_package_root", "astra_assets")
        }
        validated = _validate_inputs(
            spec, production=request["admission_mode"] == PRODUCTION_MODE)
        child_executable = _file_provenance(
            Path(sys.executable).resolve(strict=True), "child_sys_executable",
            executable=True)
        if (
            Path(child_executable["path"])
            != Path(request["executable_identity"]["path"])
            or _identity(child_executable) != request["executable_identity"]
        ):
            raise ProbeError("child_sys_executable_identity_mismatch")
        expected_ids = _expected_ids(
            request["module_closure"], request["astra_assets"],
            request["package_trees"], request["python_root_inventories"],
            request["customization_inventory"],
            request["aux_executable_closure"])
        if request.get("expected_ids") != expected_ids:
            raise ProbeError("child_expected_id_set_invalid")
        forbidden_environment = _ambient_forbidden_keys(os.environ)
        if forbidden_environment:
            raise ProbeError("child_environment_not_clean")
        if (
            not sys.flags.isolated or not sys.flags.no_site
            or not sys.dont_write_bytecode
        ):
            raise ProbeError("child_interpreter_flags_invalid")
        if "sitecustomize" in sys.modules or "usercustomize" in sys.modules:
            raise ProbeError("child_sitecustomize_loaded")
        trusted_finders = {
            importlib.machinery.BuiltinImporter,
            importlib.machinery.FrozenImporter,
            importlib.machinery.PathFinder,
        }
        if any(finder not in trusted_finders for finder in sys.meta_path):
            raise ProbeError("child_meta_path_untrusted")
        for name in request["module_closure"]:
            if name in sys.modules:
                raise ProbeError("child_module_preloaded:" + name)

        original_paths = tuple(sys.path)
        base_prefix = Path(sys.base_prefix).resolve(strict=True)
        trusted_paths: List[str] = []
        for value in original_paths:
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                continue
            try:
                resolved = candidate.resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                continue
            try:
                resolved.relative_to(base_prefix)
            except ValueError:
                continue
            if str(resolved) not in trusted_paths:
                trusted_paths.append(str(resolved))
        sys.path[:] = [
            str(validated["noetic_root"]), str(validated["system_root"]),
            *trusted_paths,
        ]

        executed_ids = ["executable", "probe_source", "python_entry"]
        python_root_directory_provenance: Dict[str, Mapping[str, Any]] = {}
        python_root_file_provenance: Dict[str, Mapping[str, Any]] = {}
        python_root_manifest_paths = set()
        for role in sorted(validated["python_root_inventories"]):
            inventory = validated["python_root_inventories"][role]
            python_root_directory_provenance[role + ":."] = (
                inventory["root_provenance"])
            executed_ids.append("python-root:" + role)
            for relative in sorted(inventory["directories"]):
                key = role + ":" + relative
                python_root_directory_provenance[key] = (
                    inventory["directories"][relative])
                executed_ids.append("python-root-directory:" + key)
            for relative in sorted(inventory["files"]):
                key = role + ":" + relative
                provenance = inventory["files"][relative]
                python_root_file_provenance[key] = provenance
                python_root_manifest_paths.add(provenance["path"])
                executed_ids.append("python-root-file:" + key)
        package_tree_file_provenance: Dict[str, Mapping[str, Any]] = {}
        for tree_id in sorted(validated["package_trees"]):
            tree = validated["package_trees"][tree_id]
            for relative in sorted(tree["files"]):
                key = tree_id + ":" + relative
                package_tree_file_provenance[key] = tree["files"][relative]
                executed_ids.append("tree:" + key)
        module_provenance: Dict[str, Mapping[str, Any]] = {}
        module_versions: Dict[str, Optional[str]] = {}
        module_loaders: Dict[str, str] = {}
        for name in sorted(request["module_closure"]):
            try:
                module = importlib.import_module(name)
            except BaseException as error:  # imports may raise arbitrary errors
                raise ProbeError(
                    "child_module_import_failed:" + name + ":" +
                    type(error).__name__) from error
            actual = _module_provenance(
                module,
                (validated["noetic_root"], validated["system_root"]), name,
                request["module_closure"][name]["loader_kind"])
            if _identity(actual) != request["module_closure"][name]["identity"]:
                raise ProbeError("child_module_identity_mismatch:" + name)
            if actual["path"] not in python_root_manifest_paths:
                raise ProbeError(
                    "child_loaded_module_not_in_root_inventory:" + name)
            module_provenance[name] = actual
            version = getattr(module, "__version__", None)
            observed_version = version if isinstance(version, str) else None
            if observed_version != request["module_closure"][name]["expected_version"]:
                raise ProbeError("child_module_version_mismatch:" + name)
            module_versions[name] = observed_version
            module_loaders[name] = type(module.__spec__.loader).__name__
            executed_ids.append("module:" + name)

        loaded_names = _loaded_nonstdlib_modules(
            (validated["noetic_root"], validated["system_root"]),
            Path(validated["source"]["path"]))
        if set(loaded_names) != set(request["module_closure"]):
            raise ProbeError("child_loaded_module_closure_incomplete")

        customization_provenance = dict(validated["customization"])
        for name in sorted(customization_provenance):
            executed_ids.append("customization:" + name)
        aux_executable_provenance = dict(validated["aux_executables"])
        for name in sorted(aux_executable_provenance):
            executed_ids.append("aux:" + name)

        asset_provenance: Dict[str, Mapping[str, Any]] = {}
        for role in ASSET_ROLES:
            actual = _reopen_identity(
                request["astra_assets"][role], "child_astra_asset:" + role,
                executable=(role == "node_executable"))
            asset_provenance[role] = actual
            executed_ids.append("asset:" + role)
        if executed_ids != expected_ids:
            raise ProbeError("child_executed_id_set_invalid")

        marker = {
            "schema_version": SCHEMA_VERSION,
            "marker": CHILD_MARKER,
            "request_id": request["request_id"],
            "request_sha256": request_provenance["sha256"],
            "status": "PASS",
            "exit_code": 0,
            "test_only": request["test_only"],
            "algorithm_validated": True,
            "validator_unit_test_pass": request["test_only"],
            "validated_pass": not request["test_only"],
            "runtime_import_probe_pass": not request["test_only"],
            "formal_consumer": False,
            "field_evidence_admitted": False,
            "delivery_ready": False,
            "expected_ids": expected_ids,
            "executed_ids": executed_ids,
            "executable_provenance": child_executable,
            "probe_source_provenance": validated["source"],
            "module_provenance": module_provenance,
            "module_versions": module_versions,
            "module_loaders": module_loaders,
            "package_tree_file_provenance": package_tree_file_provenance,
            "python_root_directory_provenance": (
                python_root_directory_provenance),
            "python_root_file_provenance": python_root_file_provenance,
            "customization_provenance": customization_provenance,
            "aux_executable_provenance": aux_executable_provenance,
            "astra_asset_provenance": asset_provenance,
            "loaded_nonstdlib_module_ids": sorted(loaded_names),
            "child_environment_keys": sorted(os.environ),
            "forbidden_environment_keys_present": [],
            "isolation": {
                "isolated": True,
                "no_site": True,
                "dont_write_bytecode": True,
            },
            "sitecustomize_loaded": False,
            "failures": [],
        }
        return marker, 0
    except ProbeError as error:
        failures.append(error.code)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append("child_probe_error:" + type(error).__name__)
    failed = dict(marker)
    failed["failures"] = sorted(set(failures))
    return failed, 1


def _parse_child_marker(stdout: str, stderr: str) -> Mapping[str, Any]:
    if stderr:
        raise ProbeError("probe_child_stderr_not_empty")
    lines = stdout.splitlines()
    marker_lines = [line for line in lines if line.startswith(CLI_MARKER)]
    if len(marker_lines) != 1 or lines != marker_lines:
        raise ProbeError("probe_child_marker_count_invalid")
    raw = marker_lines[0][len(CLI_MARKER):].encode("utf-8")
    try:
        marker = _strict_json_bytes(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise ProbeError("probe_child_marker_json_invalid") from error
    if not isinstance(marker, Mapping) or set(marker) != _CHILD_KEYS:
        raise ProbeError("probe_child_marker_schema_invalid")
    return marker


def _validate_completed(
        completed: subprocess.CompletedProcess, request: Mapping[str, Any],
        request_identity: Mapping[str, Any], validated: Mapping[str, Any]
) -> Tuple[Optional[Mapping[str, Any]], List[str]]:
    failures: List[str] = []
    try:
        marker = _parse_child_marker(completed.stdout, completed.stderr)
    except ProbeError as error:
        return None, [error.code]
    if completed.returncode != 0:
        failures.append("probe_child_nonzero_exit")
    expected_modules = {
        name: _identity(value) for name, value in validated["modules"].items()}
    expected_module_specs = validated["module_specs"]
    expected_assets = {
        role: _identity(value) for role, value in validated["assets"].items()}
    expected_tree_specs = request["package_trees"]
    expected_customization = request["customization_inventory"]
    expected_aux = request["aux_executable_closure"]
    expected_ids = _expected_ids(
        expected_module_specs, expected_assets, expected_tree_specs,
        request["python_root_inventories"], expected_customization,
        expected_aux)
    test_only = request["test_only"]
    expected_scalars = {
        "schema_version": SCHEMA_VERSION,
        "marker": CHILD_MARKER,
        "request_id": request["request_id"],
        "request_sha256": request_identity["sha256"],
        "status": "PASS",
        "exit_code": 0,
        "test_only": test_only,
        "algorithm_validated": True,
        "validator_unit_test_pass": test_only,
        "validated_pass": not test_only,
        "runtime_import_probe_pass": not test_only,
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
        "expected_ids": expected_ids,
        "executed_ids": expected_ids,
        "forbidden_environment_keys_present": [],
        "isolation": {
            "isolated": True, "no_site": True, "dont_write_bytecode": True},
        "sitecustomize_loaded": False,
        "failures": [],
    }
    for key, expected in expected_scalars.items():
        if marker.get(key) != expected:
            failures.append("probe_child_marker_semantic_mismatch:" + key)
    for key, expected in (
        ("executable_provenance", validated["executable"]),
        ("probe_source_provenance", validated["source"]),
    ):
        if marker.get(key) != expected:
            failures.append("probe_child_marker_semantic_mismatch:" + key)
    if marker.get("module_provenance") != validated["modules"]:
        failures.append("probe_child_module_provenance_mismatch")
    expected_tree_provenance = {
        tree_id + ":" + relative: provenance
        for tree_id, tree in validated["package_trees"].items()
        for relative, provenance in tree["files"].items()
    }
    if marker.get("package_tree_file_provenance") != expected_tree_provenance:
        failures.append("probe_child_package_tree_provenance_mismatch")
    expected_root_directories = {
        role + ":.": inventory["root_provenance"]
        for role, inventory in validated["python_root_inventories"].items()
    }
    expected_root_directories.update({
        role + ":" + relative: provenance
        for role, inventory in validated["python_root_inventories"].items()
        for relative, provenance in inventory["directories"].items()
    })
    expected_root_files = {
        role + ":" + relative: provenance
        for role, inventory in validated["python_root_inventories"].items()
        for relative, provenance in inventory["files"].items()
    }
    if marker.get("python_root_directory_provenance") != expected_root_directories:
        failures.append("probe_child_python_root_directory_provenance_mismatch")
    if marker.get("python_root_file_provenance") != expected_root_files:
        failures.append("probe_child_python_root_file_provenance_mismatch")
    if marker.get("customization_provenance") != validated["customization"]:
        failures.append("probe_child_customization_provenance_mismatch")
    if marker.get("aux_executable_provenance") != validated["aux_executables"]:
        failures.append("probe_child_aux_executable_provenance_mismatch")
    if marker.get("astra_asset_provenance") != validated["assets"]:
        failures.append("probe_child_astra_provenance_mismatch")
    if marker.get("loaded_nonstdlib_module_ids") != sorted(expected_modules):
        failures.append("probe_child_loaded_module_set_mismatch")
    if (
        not isinstance(marker.get("module_versions"), Mapping)
        or set(marker["module_versions"]) != set(expected_modules)
        or not isinstance(marker.get("module_loaders"), Mapping)
        or set(marker["module_loaders"]) != set(expected_modules)
        or any(
            marker["module_loaders"].get(name)
            != expected_module_specs[name]["loader_kind"]
            or marker["module_versions"].get(name)
            != expected_module_specs[name]["expected_version"]
            for name in expected_modules)
    ):
        failures.append("probe_child_module_report_invalid")
    environment_keys = marker.get("child_environment_keys")
    if (
        not isinstance(environment_keys, list)
        or any(not isinstance(value, str) for value in environment_keys)
        or _ambient_forbidden_keys({key: "" for key in environment_keys})
    ):
        failures.append("probe_child_environment_report_invalid")
    for value in marker.get("failures", []):
        if isinstance(value, str):
            failures.append("probe_child_reported_failure:" + value)
    return marker, sorted(set(failures))


def _blocked_report(mode: str, failures: Sequence[str]) -> Mapping[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "admission_mode": mode,
        "read_only": True,
        "starts_ros_graph": False,
        "opens_camera": False,
        "runs_inference": False,
        "authorizes_motion": False,
        "publishes_ros_messages": False,
        "algorithm_validated": False,
        "validator_unit_test_pass": False,
        "validated_pass": False,
        "runtime_import_probe_pass": False,
        "formal_consumer": False,
        "field_evidence_admitted": False,
        "delivery_ready": False,
        "argv": [],
        "expected_ids": [],
        "executed_ids": [],
        "request_identity": None,
        "child_marker": None,
        "parent_environment_restored": True,
        "failures": sorted(set(failures)),
    }


def run_camera_runtime_import_probe(
        *, admission_mode: str,
        executable_identity: Optional[Mapping[str, Any]] = None,
        probe_source_identity: Optional[Mapping[str, Any]] = None,
        noetic_python_root: Optional[Path] = None,
        system_python_root: Optional[Path] = None,
        vendor_install_prefix: Optional[Path] = None,
        module_closure: Optional[Mapping[str, Mapping[str, Any]]] = None,
        package_trees: Optional[Mapping[str, Mapping[str, Any]]] = None,
        python_root_inventories: Optional[
            Mapping[str, Mapping[str, Any]]] = None,
        customization_inventory: Optional[Mapping[str, Mapping[str, Any]]] = None,
        aux_executable_closure: Optional[Mapping[str, Mapping[str, Any]]] = None,
        python_entry_path: Optional[Path] = None,
        python_entry_link_text: Optional[str] = None,
        astra_package_root: Optional[Path] = None,
        astra_assets: Optional[Mapping[str, Mapping[str, Any]]] = None,
        timeout_sec: float = 60.0,
        subprocess_runner: Optional[Any] = None,
) -> Mapping[str, Any]:
    """Run the exact isolated import probe or return a fail-closed report."""
    if admission_mode not in {TEST_ONLY_MODE, PRODUCTION_MODE}:
        return _blocked_report(admission_mode, ["probe_admission_mode_invalid"])
    if admission_mode == PRODUCTION_MODE:
        if subprocess_runner is not None:
            return _blocked_report(
                admission_mode, ["probe_production_runner_injection_forbidden"])
        if any(value is not None for value in (
                executable_identity, probe_source_identity,
                noetic_python_root, system_python_root, vendor_install_prefix,
                module_closure, package_trees, python_root_inventories,
                customization_inventory,
                aux_executable_closure, python_entry_path,
                python_entry_link_text, astra_package_root, astra_assets)):
            return _blocked_report(
                admission_mode, ["probe_production_caller_spec_forbidden"])
        if not _production_spec_anchor_bound():
            return _blocked_report(
                admission_mode, ["production_runtime_import_probe_not_anchored"])
        try:
            _attest_production_parent()
            source_identity = _identity(
                _file_provenance(Path(__file__), "probe_source"))
            spec = _load_external_production_spec(
                Path(str(PRODUCTION_SPEC_PATH)),
                int(PRODUCTION_SPEC_SIZE_BYTES),
                str(PRODUCTION_SPEC_SHA256),
                Path(str(PRODUCTION_SPEC_TRUST_ROOT)),
                int(PRODUCTION_SPEC_OWNER_UID), source_identity)
        except ProbeError as error:
            return _blocked_report(admission_mode, [error.code])
    else:
        spec = {
            "executable_identity": executable_identity,
            "probe_source_identity": probe_source_identity,
            "noetic_python_root": (
                str(noetic_python_root) if noetic_python_root is not None else None),
            "system_python_root": (
                str(system_python_root) if system_python_root is not None else None),
            "vendor_install_prefix": (
                str(vendor_install_prefix) if vendor_install_prefix is not None else None),
            "module_closure": module_closure,
            "package_trees": package_trees,
            "python_root_inventories": python_root_inventories,
            "customization_inventory": customization_inventory,
            "aux_executable_closure": aux_executable_closure,
            "python_entry_path": (
                str(python_entry_path) if python_entry_path is not None else None),
            "python_entry_link_text": python_entry_link_text,
            "astra_package_root": (
                str(astra_package_root) if astra_package_root is not None else None),
            "astra_assets": astra_assets,
        }
    forbidden = _ambient_forbidden_keys(os.environ)
    if forbidden:
        return _blocked_report(
            admission_mode,
            ["probe_ambient_environment_forbidden:" + key for key in forbidden])
    if (
        isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float))
        or timeout_sec <= 0
    ):
        return _blocked_report(admission_mode, ["probe_timeout_invalid"])
    try:
        validated = _validate_inputs(
            spec, production=(admission_mode == PRODUCTION_MODE))
        request = _request(spec, validated, admission_mode)
    except ProbeError as error:
        return _blocked_report(admission_mode, [error.code])
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return _blocked_report(
            admission_mode, ["probe_parent_input_invalid:" + type(error).__name__])

    runner = subprocess.run if subprocess_runner is None else subprocess_runner
    with tempfile.TemporaryDirectory(prefix="limo_ros1_runtime_import_probe_") as temp:
        request_path = Path(temp) / "request.json"
        request_path.write_bytes(_json_bytes(request))
        request_identity = _identity(
            _file_provenance(request_path, "probe_request"))
        argv = [
            validated["executable"]["path"], "-I", "-S", "-B",
            validated["source"]["path"], "--child-request", str(request_path),
        ]
        child_environment = _clean_child_environment(os.environ)
        environment_snapshot = dict(os.environ)
        path_snapshot = tuple(sys.path)
        meta_path_snapshot = tuple(sys.meta_path)
        modules_snapshot = dict(sys.modules)
        execution_failures: List[str] = []
        try:
            completed = runner(
                argv, cwd=temp, env=child_environment, capture_output=True,
                text=True, encoding="utf-8", errors="strict",
                timeout=float(timeout_sec), check=False)
        except subprocess.TimeoutExpired:
            completed = subprocess.CompletedProcess(
                argv, 124, stdout="", stderr="")
            execution_failures.append("probe_child_timeout")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            completed = subprocess.CompletedProcess(
                argv, 127, stdout="", stderr="")
            execution_failures.append(
                "probe_child_spawn_failed:" + type(error).__name__)
        environment_restored = (
            dict(os.environ) == environment_snapshot
            and tuple(sys.path) == path_snapshot
            and tuple(sys.meta_path) == meta_path_snapshot
            and all(sys.modules.get(key) is value for key, value in modules_snapshot.items())
            and all(key in modules_snapshot for key in sys.modules)
        )
        marker, marker_failures = _validate_completed(
            completed, request, request_identity, validated)
        post_failures: List[str] = []
        for role, before in (
            [("executable", validated["executable"]),
             ("probe_source", validated["source"])]
            + [("module:" + name, value) for name, value in validated["modules"].items()]
            + [
                ("tree:" + tree_id + ":" + relative, value)
                for tree_id, tree in validated["package_trees"].items()
                for relative, value in tree["files"].items()]
            + [("customization:" + name, value)
               for name, value in validated["customization"].items()]
            + [("aux:" + name, value)
               for name, value in validated["aux_executables"].items()]
            + [("asset:" + role, value) for role, value in validated["assets"].items()]
        ):
            try:
                after = _file_provenance(
                    Path(before["path"]), "probe_post_identity:" + role,
                    executable=(role in {"executable", "asset:node_executable"}))
                if after != before:
                    post_failures.append("probe_bound_artifact_drift:" + role)
            except ProbeError:
                post_failures.append("probe_bound_artifact_drift:" + role)
        for tree_id, tree in validated["package_trees"].items():
            try:
                after_tree = _enumerate_regular_tree(
                    Path(tree["root_path"]), "probe_post_tree:" + tree_id)
                if after_tree != tree["files"]:
                    post_failures.append("probe_package_tree_drift:" + tree_id)
            except ProbeError:
                post_failures.append("probe_package_tree_drift:" + tree_id)
        for role, inventory in validated["python_root_inventories"].items():
            try:
                after_inventory = _enumerate_exact_python_root(
                    Path(inventory["root_path"]),
                    "probe_post_python_root:" + role)
                if after_inventory != inventory:
                    post_failures.append(
                        "probe_python_root_inventory_drift:" + role)
            except ProbeError:
                post_failures.append(
                    "probe_python_root_inventory_drift:" + role)
        try:
            if _scan_customization_files(
                    validated["noetic_root"], validated["system_root"]
            ) != validated["customization"]:
                post_failures.append("probe_customization_inventory_drift")
        except ProbeError:
            post_failures.append("probe_customization_inventory_drift")
        try:
            after_entry = _validate_python_entry(
                request["python_entry_path"],
                request["python_entry_link_text"], validated["executable"])
            if after_entry != validated["python_entry"]:
                post_failures.append("probe_python_entry_drift")
        except ProbeError:
            post_failures.append("probe_python_entry_drift")
        failures = sorted(set(
            execution_failures + marker_failures + post_failures
            + ([] if environment_restored else ["probe_parent_environment_not_restored"])))
        expected_ids = request["expected_ids"]
        executed_ids = (
            marker.get("executed_ids", []) if isinstance(marker, Mapping) else [])
        algorithm_validated = not failures
        report = _blocked_report(admission_mode, failures)
        report.update({
            "algorithm_validated": algorithm_validated,
            "validator_unit_test_pass": (
                algorithm_validated and admission_mode == TEST_ONLY_MODE),
            # Only the immutable PRODUCTION_SPEC path can make these true;
            # the current generation leaves that spec unset.
            "validated_pass": (
                algorithm_validated and admission_mode == PRODUCTION_MODE),
            "runtime_import_probe_pass": (
                algorithm_validated and admission_mode == PRODUCTION_MODE),
            "argv": argv,
            "expected_ids": expected_ids,
            "executed_ids": executed_ids,
            "request_identity": request_identity,
            "child_marker": marker,
            "parent_environment_restored": environment_restored,
        })
        return report


def _parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child-request", type=Path)
    return parser.parse_args(args)


def _main(args: Optional[Sequence[str]] = None) -> int:
    parsed = _parse_args(args)
    if parsed.child_request is not None:
        marker, exit_code = _child_execute(parsed.child_request)
        sys.stdout.write(CLI_MARKER + _json_bytes(marker).decode("utf-8") + "\n")
        sys.stdout.flush()
        return exit_code
    report = run_camera_runtime_import_probe(admission_mode=PRODUCTION_MODE)
    sys.stdout.write(CLI_MARKER + _json_bytes(report).decode("utf-8") + "\n")
    sys.stdout.flush()
    return 0 if report["validated_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
