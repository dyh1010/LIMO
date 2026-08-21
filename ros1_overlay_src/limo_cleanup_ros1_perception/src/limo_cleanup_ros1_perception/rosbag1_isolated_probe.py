"""Isolated, read-only ROS1 rosbag reader provenance probe.

The parent starts this exact file with an externally anchored, versioned
interpreter target in a fresh ``-I -S -B`` process.  A trusted entry symlink
such as ``/usr/bin/python3`` may launch the parent, but its complete link chain
and resolved regular-file target are checked before and after the child run.
The child imports ``rosbag`` only from an explicitly declared
Noetic prefix, records its exact module identity, and writes one exclusive
JSON artifact containing decoded formal-index material plus exact raw record
evidence.  This module does not start ROS, join a graph, repair a bag, or
authorize delivery.  Every probe artifact remains denominator-excluded and
can never claim formal acceptance; only the host final-readiness authority may
promote independently revalidated material after install/runtime admission.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


REQUEST_MARKER = "LIMO_ROS1_ISOLATED_BAG_PROBE_REQUEST_V1"
CHILD_MARKER = "LIMO_ROS1_ISOLATED_BAG_PROBE_CHILD_V1"
ARTIFACT_MARKER = "LIMO_ROS1_ISOLATED_BAG_RAW_ARTIFACT_V1"
GATE_ID = "ROS1_NOETIC_ISOLATED_ROSBAG_READER_PROBE"
ROSBAG1_V2_MAGIC = b"#ROSBAG V2.0\n"
DEFAULT_PYTHON_ROOT_RELATIVE = "lib/python3/dist-packages"
DEFAULT_MAX_MESSAGES = 100000
DEFAULT_MAX_TOTAL_PAYLOAD_BYTES = 1024 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 300.0

_IDENTITY_KEYS = {"path", "size_bytes", "sha256"}
_EXECUTABLE_ADMISSION_KEYS = {"entry_path", "chain", "target_identity"}
_EXECUTABLE_CHAIN_KEYS = {
    "path", "kind", "link_target", "mode", "device", "inode"
}
_REQUEST_KEYS = {
    "schema_version",
    "marker",
    "request_id",
    "bag_identity",
    "noetic_prefix",
    "python_root_relative",
    "rosbag_module_identity",
    "rosbag_decoder_closure",
    "indexer_module_identity",
    "formal_manifest_identity",
    "probe_source_identity",
    "sys_executable_identity",
    "parent_executable_admission",
    "capture_id",
    "scene",
    "trusted_system_python_roots",
    "test_only",
    "output_path",
    "max_messages",
    "max_total_payload_bytes",
}
_CHILD_MARKER_KEYS = {
    "schema_version",
    "marker",
    "request_id",
    "request_sha256",
    "status",
    "exit_code",
    "bag_identity",
    "noetic_prefix",
    "python_root",
    "rosbag_module_identity",
    "indexer_module_identity",
    "formal_manifest_identity",
    "probe_source_identity",
    "sys_executable_identity",
    "child_executable_admission",
    "output_identity",
    "connection_count",
    "message_count",
    "total_payload_bytes",
    "formal_report_sha256",
    "loaded_nonstdlib_module_set_sha256",
    "test_only",
    "algorithm_validated",
    "formal_acceptance",
    "not_in_four_scene_denominator",
    "forbidden_environment_keys_present",
    "failures",
}
_ARTIFACT_KEYS = {
    "schema_version",
    "marker",
    "report_kind",
    "read_only",
    "authorizes_motion",
    "publishes_ros_messages",
    "delivery_ready",
    "request_id",
    "request_sha256",
    "bag_identity",
    "noetic_prefix",
    "python_root",
    "rosbag_module_identity",
    "indexer_module_identity",
    "formal_manifest_identity",
    "probe_source_identity",
    "sys_executable_identity",
    "parent_executable_admission",
    "child_executable_admission",
    "capture_id",
    "scene",
    "connections",
    "messages",
    "connection_count",
    "message_count",
    "total_payload_bytes",
    "formal_report",
    "loaded_nonstdlib_module_provenance",
    "test_only",
    "algorithm_validated",
    "formal_acceptance",
    "not_in_four_scene_denominator",
}
_FORBIDDEN_ENVIRONMENT_EXACT = {
    "PYTHONHOME",
    "PYTHONPATH",
    "CMAKE_PREFIX_PATH",
    "COLCON_PREFIX_PATH",
    "AMENT_PREFIX_PATH",
}
_FORBIDDEN_ENVIRONMENT_PREFIXES = ("ROS_", "CATKIN_", "COLCON_", "AMENT_")
_CHILD_ENVIRONMENT_ALLOWLIST = {
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
}


class ProbeError(ValueError):
    """A stable fail-closed probe error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise ValueError("nonfinite_json_number:" + value)


def _strict_json_bytes(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_nonfinite,
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_component_is_linklike(path: Path) -> bool:
    metadata = os.lstat(str(path))
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        reparse_flag
        and getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _path_has_linklike_component(path: Path) -> bool:
    candidate = Path(path).absolute()
    chain = list(reversed(candidate.parents)) + [candidate]
    try:
        return any(_path_component_is_linklike(item) for item in chain)
    except (OSError, RuntimeError, ValueError):
        return True


def _regular_file_identity(path: Path) -> Mapping[str, Any]:
    candidate = Path(path)
    try:
        os.lstat(str(candidate.absolute()))
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError("artifact_missing") from error
    if _path_has_linklike_component(candidate):
        raise ProbeError("artifact_path_linklike")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = os.lstat(str(resolved))
    except (OSError, RuntimeError, ValueError) as error:
        raise ProbeError("artifact_missing") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ProbeError("artifact_not_regular_file")
    if int(getattr(metadata, "st_nlink", 1)) != 1:
        raise ProbeError("artifact_hardlink_forbidden")
    return {
        "path": str(resolved),
        "size_bytes": int(metadata.st_size),
        "sha256": _sha256_file(resolved),
    }


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without following symlinks."""
    return Path(os.path.abspath(str(Path(path))))


def _executable_chain_item(
    path: Path, metadata: os.stat_result, kind: str, link_target: Optional[str]
) -> Mapping[str, Any]:
    return {
        "path": str(_lexical_absolute(path)),
        "kind": kind,
        "link_target": link_target,
        "mode": int(metadata.st_mode),
        "device": int(getattr(metadata, "st_dev", 0)),
        "inode": int(getattr(metadata, "st_ino", 0)),
    }


def _admit_executable_entry(
    entry_path: Path, expected_target_identity: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Bind one entry path and its symlink chain to an external target anchor."""
    if not _valid_identity(expected_target_identity):
        raise ProbeError("probe_executable_anchor_invalid")
    try:
        anchored_target = _regular_file_identity(
            Path(expected_target_identity["path"])
        )
    except ProbeError as error:
        raise ProbeError("probe_executable_anchor_invalid") from error
    if not _identity_matches(anchored_target, expected_target_identity):
        raise ProbeError("probe_executable_target_identity_mismatch")

    entry = _lexical_absolute(entry_path)
    for ancestor in reversed(entry.parents):
        try:
            metadata = os.lstat(str(ancestor))
        except (OSError, RuntimeError, ValueError) as error:
            raise ProbeError("probe_executable_entry_ancestor_invalid") from error
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or (
                reparse_flag
                and getattr(metadata, "st_file_attributes", 0) & reparse_flag
            )
        ):
            raise ProbeError("probe_executable_entry_ancestor_linklike")

    chain: List[Mapping[str, Any]] = []
    seen = set()
    current = entry
    for _depth in range(64):
        key = os.path.normcase(str(_lexical_absolute(current)))
        if key in seen:
            raise ProbeError("probe_executable_entry_loop")
        seen.add(key)
        try:
            metadata = os.lstat(str(current))
        except (OSError, RuntimeError, ValueError) as error:
            if chain:
                raise ProbeError("probe_executable_entry_broken_link") from error
            raise ProbeError("probe_executable_entry_missing") from error
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        reparse = bool(
            reparse_flag
            and getattr(metadata, "st_file_attributes", 0) & reparse_flag
        )
        if stat.S_ISLNK(metadata.st_mode):
            try:
                raw_target = os.readlink(str(current))
            except (OSError, RuntimeError, ValueError) as error:
                raise ProbeError("probe_executable_entry_readlink_failed") from error
            target_path = Path(raw_target)
            if not target_path.is_absolute() and ".." in target_path.parts:
                raise ProbeError("probe_executable_entry_relative_escape")
            chain.append(
                _executable_chain_item(
                    current, metadata, "symlink", str(raw_target)
                )
            )
            current = _lexical_absolute(
                target_path if target_path.is_absolute()
                else current.parent / target_path
            )
            continue
        if reparse:
            raise ProbeError("probe_executable_entry_reparse_forbidden")
        if not stat.S_ISREG(metadata.st_mode):
            raise ProbeError("probe_executable_target_not_regular")
        if os.name != "nt" and not (
            metadata.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ):
            raise ProbeError("probe_executable_target_not_executable")
        try:
            target_identity = _regular_file_identity(current)
        except ProbeError as error:
            raise ProbeError("probe_executable_target_invalid") from error
        chain.append(
            _executable_chain_item(current, metadata, "regular_target", None)
        )
        if target_identity != anchored_target:
            raise ProbeError("probe_executable_target_identity_mismatch")
        return {
            "entry_path": str(entry),
            "chain": chain,
            "target_identity": target_identity,
        }
    raise ProbeError("probe_executable_entry_chain_too_deep")


def _valid_executable_admission(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) != _EXECUTABLE_ADMISSION_KEYS
        or not isinstance(value.get("entry_path"), str)
        or not Path(value["entry_path"]).is_absolute()
        or not isinstance(value.get("chain"), list)
        or not value["chain"]
        or not _valid_identity(value.get("target_identity"))
    ):
        return False
    for item in value["chain"]:
        if (
            not isinstance(item, Mapping)
            or set(item) != _EXECUTABLE_CHAIN_KEYS
            or not isinstance(item.get("path"), str)
            or not Path(item["path"]).is_absolute()
            or item.get("kind") not in {"symlink", "regular_target"}
            or (
                item["kind"] == "symlink"
                and not isinstance(item.get("link_target"), str)
            )
            or (
                item["kind"] == "regular_target"
                and item.get("link_target") is not None
            )
            or any(
                type(item.get(key)) is not int
                for key in ("mode", "device", "inode")
            )
        ):
            return False
    return (
        value["chain"][-1].get("kind") == "regular_target"
        and value["chain"][-1].get("path")
        == value["target_identity"].get("path")
    )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_identity(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _IDENTITY_KEYS
        and isinstance(value.get("path"), str)
        and bool(value.get("path"))
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] >= 0
        and _valid_sha256(value.get("sha256"))
    )


def _identity_matches(actual: Mapping[str, Any], expected: Any) -> bool:
    return _valid_identity(expected) and all(
        actual.get(key) == expected.get(key) for key in _IDENTITY_KEYS
    )


def _validate_decoder_closure(
    value: Any, python_root: Path
) -> Mapping[str, Mapping[str, Any]]:
    if (
        not isinstance(value, Mapping)
        or set(value) < {"rosbag", "rosbag.bag"}
        or any(
            not isinstance(name, str)
            or not (name == "rosbag" or name.startswith("rosbag."))
            or not _valid_identity(identity)
            for name, identity in value.items()
        )
    ):
        raise ProbeError("rosbag_decoder_closure_invalid")
    result: Dict[str, Mapping[str, Any]] = {}
    seen_paths = set()
    for name in sorted(value):
        expected = value[name]
        actual = _regular_file_identity(Path(expected["path"]))
        if (
            not _identity_matches(actual, expected)
            or not _is_under(Path(actual["path"]), python_root)
            or actual["path"] in seen_paths
        ):
            raise ProbeError("rosbag_decoder_closure_identity_mismatch")
        seen_paths.add(actual["path"])
        result[name] = dict(actual)
    return result


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _normalise_header(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ProbeError("rosbag_connection_header_invalid")
    result: Dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(item, bytes):
            item = item.decode("utf-8")
        if not isinstance(key, str) or not isinstance(item, str) or key in result:
            raise ProbeError("rosbag_connection_header_invalid")
        result[key] = item
    return result


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _deterministic_request_id(value: Mapping[str, Any]) -> str:
    """Bind a probe request to all canonical material except its own ID."""
    if not isinstance(value, Mapping):
        raise ProbeError("probe_request_schema_invalid")
    material = dict(value)
    material.pop("request_id", None)
    return _canonical_sha256(material)


def _raw_message_parts(value: Any) -> Tuple[Any, Any, Any, Any, Any]:
    if isinstance(value, tuple) and len(value) == 5:
        return value
    if (
        isinstance(value, tuple)
        and len(value) == 3
        and isinstance(value[1], tuple)
        and len(value[1]) == 3
    ):
        data, md5sum, position = value[1]
        return value[0], data, md5sum, position, value[2]
    for names in (
        ("datatype", "data", "md5sum", "position", "pytype"),
        ("type", "data", "md5sum", "position", "pytype"),
    ):
        if all(hasattr(value, name) for name in names):
            return tuple(getattr(value, name) for name in names)
    raise ProbeError("rosbag_raw_message_shape_invalid")


def _stamp_ns(value: Any) -> int:
    if hasattr(value, "to_nsec"):
        result = value.to_nsec()
    elif hasattr(value, "secs") and hasattr(value, "nsecs"):
        result = int(value.secs) * 1_000_000_000 + int(value.nsecs)
    else:
        raise ProbeError("rosbag_record_stamp_invalid")
    if type(result) is not int or result < 0:
        raise ProbeError("rosbag_record_stamp_invalid")
    return result


def _module_identity(module: Any, root: Path) -> Mapping[str, Any]:
    path = getattr(module, "__file__", None)
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    if not isinstance(path, str) or not isinstance(origin, str):
        raise ProbeError("rosbag_module_origin_invalid")
    identity = _regular_file_identity(Path(path))
    origin_identity = _regular_file_identity(Path(origin))
    if identity != origin_identity or not _is_under(Path(path), root):
        raise ProbeError("rosbag_module_origin_invalid")
    return identity


def _loaded_nonstdlib_provenance(
    allowed_roots: Sequence[Path], exact_files: Sequence[Path]
) -> List[Mapping[str, Any]]:
    stdlib_roots = [Path(value) for value in _trusted_stdlib_paths()]
    exact = {str(Path(value).resolve(strict=True)) for value in exact_files}
    records = []
    seen_paths = set()
    for name, module in sorted(sys.modules.items()):
        path_value = getattr(module, "__file__", None)
        if not isinstance(path_value, str):
            continue
        try:
            path = Path(path_value).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise ProbeError("loaded_module_origin_invalid")
        if any(_is_under(path, root) for root in stdlib_roots):
            continue
        if str(path) not in exact and not any(
            _is_under(path, root) for root in allowed_roots
        ):
            raise ProbeError("loaded_module_outside_trusted_roots")
        identity = _regular_file_identity(path)
        key = (name, identity["path"])
        if key in seen_paths:
            continue
        seen_paths.add(key)
        records.append({"module": name, **identity})
    names = {item["module"] for item in records}
    if "rosbag" not in names or "rosbag.bag" not in names:
        raise ProbeError("rosbag_module_closure_incomplete")
    return records


def _pytype_identity(pytype: Any, root: Path) -> Mapping[str, Any]:
    module_name = getattr(pytype, "__module__", None)
    qualname = getattr(pytype, "__qualname__", getattr(pytype, "__name__", None))
    module = sys.modules.get(module_name) if isinstance(module_name, str) else None
    if module is None or not isinstance(qualname, str) or not qualname:
        raise ProbeError("ros_message_type_origin_invalid")
    identity = _module_identity(module, root)
    return {
        "module": module_name,
        "qualname": qualname,
        "path": identity["path"],
        "size_bytes": identity["size_bytes"],
        "sha256": identity["sha256"],
    }


def _trusted_stdlib_paths() -> List[str]:
    candidates = []
    for name in ("stdlib", "platstdlib"):
        value = sysconfig.get_path(name)
        if isinstance(value, str) and value:
            candidates.append(str(Path(value).resolve()))
            dynamic = Path(value) / "lib-dynload"
            if dynamic.is_dir():
                candidates.append(str(dynamic.resolve()))
    # CPython on Windows keeps stdlib extension modules (for example
    # ``_hashlib.pyd``) beside ``Lib`` in the interpreter-owned ``DLLs``
    # directory rather than in ``lib-dynload``.
    windows_dlls = Path(sys.base_prefix) / "DLLs"
    if windows_dlls.is_dir():
        candidates.append(str(windows_dlls.resolve()))
    return list(dict.fromkeys(candidates))


def _load_exact_rosbag(
    python_root: Path,
    expected_identity: Mapping[str, Any],
    trusted_system_roots: Sequence[str] = (),
) -> Tuple[Any, Mapping[str, Any]]:
    expected_path = Path(expected_identity["path"])
    if not _is_under(expected_path, python_root):
        raise ProbeError("rosbag_module_outside_noetic_prefix")
    for name in tuple(sys.modules):
        if name == "rosbag" or name.startswith("rosbag."):
            sys.modules.pop(name, None)
    sys.meta_path[:] = [
        importlib.machinery.BuiltinImporter,
        importlib.machinery.FrozenImporter,
        importlib.machinery.PathFinder,
    ]
    sys.path[:] = (
        _trusted_stdlib_paths() + list(trusted_system_roots) + [str(python_root)]
    )
    spec = importlib.machinery.PathFinder.find_spec("rosbag", [str(python_root)])
    if (
        spec is None
        or spec.loader is None
        or not isinstance(spec.loader, importlib.machinery.SourceFileLoader)
        or not isinstance(spec.origin, str)
    ):
        raise ProbeError("rosbag_module_spec_invalid")
    if Path(spec.origin).resolve(strict=True) != expected_path.resolve(strict=True):
        raise ProbeError("rosbag_module_origin_invalid")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rosbag"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop("rosbag", None)
        raise ProbeError("rosbag_module_import_failed") from error
    actual = _module_identity(module, python_root)
    if not _identity_matches(actual, expected_identity):
        raise ProbeError("rosbag_module_identity_mismatch")
    package_path = getattr(module, "__path__", None)
    expected_package = expected_path.parent.resolve(strict=True)
    if (
        not isinstance(package_path, Sequence)
        or isinstance(package_path, (str, bytes))
        or [str(Path(item).resolve(strict=True)) for item in package_path]
        != [str(expected_package)]
    ):
        raise ProbeError("rosbag_package_path_invalid")
    return module, actual


def _load_exact_source_module(
    private_name: str, expected_identity: Mapping[str, Any]
) -> Tuple[Any, Mapping[str, Any]]:
    path = Path(expected_identity["path"])
    actual = _regular_file_identity(path)
    if not _identity_matches(actual, expected_identity):
        raise ProbeError("indexer_module_identity_mismatch")
    loader = importlib.machinery.SourceFileLoader(private_name, actual["path"])
    spec = importlib.util.spec_from_file_location(
        private_name, actual["path"], loader=loader
    )
    if spec is None or spec.loader is not loader or spec.origin != actual["path"]:
        raise ProbeError("indexer_module_spec_invalid")
    module = importlib.util.module_from_spec(spec)
    sys.modules[private_name] = module
    try:
        loader.exec_module(module)
    except Exception as error:
        sys.modules.pop(private_name, None)
        raise ProbeError("indexer_module_import_failed") from error
    if (
        getattr(module, "__file__", None) != actual["path"]
        or getattr(module, "__spec__", None) is not spec
        or getattr(module, "__loader__", None) is not loader
    ):
        raise ProbeError("indexer_module_provenance_invalid")
    return module, actual


def _serialise_indexer_records(
    connections: Any, messages: Any
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], int]:
    if not isinstance(connections, list) or not isinstance(messages, list):
        raise ProbeError("indexer_reader_result_invalid")
    serialised_connections = []
    for item in connections:
        if not isinstance(item, Mapping):
            raise ProbeError("indexer_connection_record_invalid")
        candidate = dict(item)
        _json_bytes(candidate)
        serialised_connections.append(candidate)
    serialised_messages = []
    total_payload_bytes = 0
    for item in messages:
        if not isinstance(item, Mapping):
            raise ProbeError("indexer_message_record_invalid")
        candidate = dict(item)
        payload = candidate.pop("serialized_payload", None)
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        if not isinstance(payload, bytes):
            raise ProbeError("indexer_message_payload_invalid")
        total_payload_bytes += len(payload)
        candidate["serialized_payload_base64"] = base64.b64encode(
            payload
        ).decode("ascii")
        candidate["serialized_size_bytes"] = len(payload)
        candidate["serialized_sha256"] = hashlib.sha256(payload).hexdigest()
        _json_bytes(candidate)
        serialised_messages.append(candidate)
    return serialised_connections, serialised_messages, total_payload_bytes


def reconstruct_probe_records(
    artifact_path: Path,
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Any]]:
    """Reopen one probe artifact and restore exact raw message bytes."""
    artifact = _strict_json_bytes(Path(artifact_path).read_bytes())
    if not isinstance(artifact, Mapping) or set(artifact) != _ARTIFACT_KEYS:
        raise ProbeError("probe_output_schema_invalid")
    connections = artifact.get("connections")
    messages = artifact.get("messages")
    formal_report = artifact.get("formal_report")
    if (
        not isinstance(connections, list)
        or not isinstance(messages, list)
        or not isinstance(formal_report, Mapping)
    ):
        raise ProbeError("probe_output_policy_invalid")
    restored = []
    for item in messages:
        if not isinstance(item, Mapping):
            raise ProbeError("probe_output_message_invalid")
        candidate = dict(item)
        encoded = candidate.pop("serialized_payload_base64", None)
        expected_size = candidate.pop("serialized_size_bytes", None)
        expected_sha = candidate.pop("serialized_sha256", None)
        if not isinstance(encoded, str):
            raise ProbeError("probe_output_message_invalid")
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeError, ValueError) as error:
            raise ProbeError("probe_output_message_invalid") from error
        if (
            type(expected_size) is not int
            or len(payload) != expected_size
            or hashlib.sha256(payload).hexdigest() != expected_sha
        ):
            raise ProbeError("probe_output_message_identity_mismatch")
        candidate["serialized_payload"] = payload
        restored.append(candidate)
    return list(connections), restored, dict(formal_report)


def _validate_artifact_semantics(
    artifact: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    expected_python_root = str(
        (
            Path(request["noetic_prefix"])
            / request["python_root_relative"]
        ).resolve(strict=True)
    )
    test_only = request["test_only"]
    formal_report = artifact.get("formal_report")
    if (
        artifact.get("noetic_prefix")
        != str(Path(request["noetic_prefix"]).resolve(strict=True))
        or artifact.get("python_root") != expected_python_root
        or artifact.get("capture_id") != request["capture_id"]
        or artifact.get("scene") != request["scene"]
        or artifact.get("parent_executable_admission")
        != request["parent_executable_admission"]
        or not _valid_executable_admission(
            artifact.get("child_executable_admission")
        )
        or artifact["child_executable_admission"].get("target_identity")
        != artifact.get("sys_executable_identity")
        or artifact["child_executable_admission"].get("entry_path")
        != artifact.get("sys_executable_identity", {}).get("path")
        or artifact.get("test_only") is not test_only
        or artifact.get("algorithm_validated") is not True
        or artifact.get("formal_acceptance") is not False
        or artifact.get("not_in_four_scene_denominator") is not True
        or not isinstance(formal_report, Mapping)
        or formal_report.get("source_capture") != request["bag_identity"]
        or formal_report.get("capture_id") != request["capture_id"]
        or formal_report.get("scene") != request["scene"]
        or formal_report.get("delivery_ready") is not False
        or formal_report.get("formal_acceptance") is not False
        or formal_report.get("not_in_four_scene_denominator") is not True
    ):
        raise ProbeError("probe_output_policy_invalid")

    connections = artifact.get("connections")
    messages = artifact.get("messages")
    if not isinstance(connections, list) or not isinstance(messages, list):
        raise ProbeError("probe_output_policy_invalid")
    connection_ids = set()
    for item in connections:
        connection_id = item.get("connection_id") if isinstance(item, Mapping) else None
        if (
            type(connection_id) is not int
            or connection_id < 0
            or connection_id in connection_ids
        ):
            raise ProbeError("probe_output_connection_invalid")
        connection_ids.add(connection_id)
    total_payload_bytes = 0
    message_fingerprints = set()
    restored_messages = []
    for item in messages:
        if not isinstance(item, Mapping):
            raise ProbeError("probe_output_message_invalid")
        connection_id = item.get("connection_id")
        encoded = item.get("serialized_payload_base64")
        expected_size = item.get("serialized_size_bytes")
        expected_sha = item.get("serialized_sha256")
        if connection_id not in connection_ids or not isinstance(encoded, str):
            raise ProbeError("probe_output_message_invalid")
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeError, ValueError) as error:
            raise ProbeError("probe_output_message_invalid") from error
        if (
            type(expected_size) is not int
            or expected_size <= 0
            or len(payload) != expected_size
            or hashlib.sha256(payload).hexdigest() != expected_sha
        ):
            raise ProbeError("probe_output_message_identity_mismatch")
        total_payload_bytes += len(payload)
        fingerprint = _canonical_sha256(item)
        if fingerprint in message_fingerprints:
            raise ProbeError("probe_output_duplicate_message")
        message_fingerprints.add(fingerprint)
        restored = dict(item)
        restored.pop("serialized_payload_base64", None)
        restored.pop("serialized_size_bytes", None)
        restored.pop("serialized_sha256", None)
        restored["serialized_payload"] = payload
        restored_messages.append(restored)
    if (
        artifact.get("connection_count") != len(connections)
        or artifact.get("message_count") != len(messages)
        or artifact.get("total_payload_bytes") != total_payload_bytes
    ):
        raise ProbeError("probe_output_count_mismatch")

    private_name = "_limo_ros1_parent_formal_recompute_v1"
    previous_private_module = sys.modules.get(private_name)
    try:
        indexer, _identity = _load_exact_source_module(
            private_name, request["indexer_module_identity"]
        )
        manifest = indexer.load_formal_manifest(
            Path(request["formal_manifest_identity"]["path"])
        )
        recomputed = indexer.inspect_records(
            list(connections),
            restored_messages,
            request["capture_id"],
            request["scene"],
            manifest,
            request["bag_identity"],
            indexer.FORMAL_CAMERA_ONLY_MODE,
        )
        recomputed = dict(recomputed)
        recomputed["formal_acceptance"] = False
        recomputed["not_in_four_scene_denominator"] = True
        recomputed["delivery_ready"] = False
        recomputed["test_only"] = test_only
        recomputed["algorithm_validated"] = True
        if recomputed != formal_report:
            raise ProbeError("probe_output_formal_recompute_mismatch")
    except ProbeError:
        raise
    except Exception as error:
        raise ProbeError("probe_output_formal_recompute_failed") from error
    finally:
        if previous_private_module is None:
            sys.modules.pop(private_name, None)
        else:
            sys.modules[private_name] = previous_private_module

    provenance = artifact.get("loaded_nonstdlib_module_provenance")
    if not isinstance(provenance, list):
        raise ProbeError("probe_output_module_provenance_invalid")
    allowed_roots = [Path(expected_python_root)] + [
        Path(value).resolve(strict=True)
        for value in request["trusted_system_python_roots"]
    ]
    exact_files = {
        request["probe_source_identity"]["path"],
        request["indexer_module_identity"]["path"],
    }
    seen_modules = set()
    decoder_closure = {}
    for item in provenance:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"module", "path", "size_bytes", "sha256"}
            or not isinstance(item.get("module"), str)
            or item["module"] in seen_modules
        ):
            raise ProbeError("probe_output_module_provenance_invalid")
        identity = {key: item[key] for key in _IDENTITY_KEYS}
        actual = _regular_file_identity(Path(identity["path"]))
        if actual != identity or (
            identity["path"] not in exact_files
            and not any(
                _is_under(Path(identity["path"]), root)
                for root in allowed_roots
            )
        ):
            raise ProbeError("probe_output_module_provenance_invalid")
        seen_modules.add(item["module"])
        if item["module"] == "rosbag" or item["module"].startswith("rosbag."):
            decoder_closure[item["module"]] = identity
    if decoder_closure != request["rosbag_decoder_closure"]:
        raise ProbeError("rosbag_decoder_closure_identity_mismatch")


def _connection_signature(
    topic: str, datatype: str, md5sum: str, header: Mapping[str, str]
) -> Tuple[str, str, str, str, str]:
    return (
        topic,
        datatype,
        md5sum,
        header.get("callerid", ""),
        header.get("latching", ""),
    )


def _read_bag(
    rosbag: Any,
    bag_path: Path,
    python_root: Path,
    max_messages: int,
    max_total_payload_bytes: int,
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], int]:
    try:
        bag = rosbag.Bag(str(bag_path), mode="r", allow_unindexed=False)
    except Exception as error:
        raise ProbeError("rosbag_open_failed") from error
    try:
        if getattr(bag, "version", None) != 200:
            raise ProbeError("rosbag_version_invalid")
        if not hasattr(bag, "_get_connections"):
            raise ProbeError("rosbag_connection_api_unavailable")
        connections: List[Mapping[str, Any]] = []
        signature_to_id: Dict[Tuple[str, str, str, str, str], int] = {}
        for info in list(bag._get_connections()):
            header = _normalise_header(getattr(info, "header", None))
            connection_id = getattr(info, "id", None)
            topic = str(getattr(info, "topic", ""))
            datatype = str(getattr(info, "datatype", ""))
            md5sum = str(getattr(info, "md5sum", ""))
            if type(connection_id) is not int or connection_id < 0:
                raise ProbeError("rosbag_connection_id_invalid")
            if not topic or not datatype or not md5sum:
                raise ProbeError("rosbag_connection_schema_invalid")
            signature = _connection_signature(topic, datatype, md5sum, header)
            if signature in signature_to_id:
                raise ProbeError("rosbag_duplicate_connection")
            signature_to_id[signature] = connection_id
            connections.append(
                {
                    "connection_id": connection_id,
                    "topic": topic,
                    "type": datatype,
                    "md5sum": md5sum,
                    "connection_header": dict(header),
                    "connection_header_sha256": _canonical_sha256(header),
                }
            )
        messages: List[Mapping[str, Any]] = []
        total_payload_bytes = 0
        iterator = bag.read_messages(raw=True, return_connection_header=True)
        for index, item in enumerate(iterator):
            if index >= max_messages:
                raise ProbeError("rosbag_message_limit_exceeded")
            if not isinstance(item, tuple) or len(item) != 4:
                raise ProbeError("rosbag_message_tuple_invalid")
            topic, raw_message, stamp, raw_header = item
            datatype, data, md5sum, _position, pytype = _raw_message_parts(
                raw_message
            )
            if isinstance(data, memoryview):
                data = data.tobytes()
            if not isinstance(data, bytes):
                try:
                    data = bytes(data)
                except (TypeError, ValueError) as error:
                    raise ProbeError("rosbag_payload_invalid") from error
            total_payload_bytes += len(data)
            if total_payload_bytes > max_total_payload_bytes:
                raise ProbeError("rosbag_payload_limit_exceeded")
            header = _normalise_header(raw_header)
            topic = str(topic)
            datatype = str(datatype)
            md5sum = str(md5sum)
            signature = _connection_signature(topic, datatype, md5sum, header)
            connection_id = signature_to_id.get(signature)
            if connection_id is None:
                raise ProbeError("rosbag_message_connection_mismatch")
            messages.append(
                {
                    "message_index": index,
                    "connection_id": connection_id,
                    "topic": topic,
                    "type": datatype,
                    "md5sum": md5sum,
                    "record_timestamp_ns": _stamp_ns(stamp),
                    "connection_header": dict(header),
                    "connection_header_sha256": _canonical_sha256(header),
                    "serialized_payload_base64": base64.b64encode(data).decode(
                        "ascii"
                    ),
                    "serialized_size_bytes": len(data),
                    "serialized_sha256": hashlib.sha256(data).hexdigest(),
                    "message_type_identity": _pytype_identity(
                        pytype, python_root
                    ),
                }
            )
        return connections, messages, total_payload_bytes
    finally:
        try:
            bag.close()
        except Exception:
            pass


def _forbidden_environment_keys(environment: Mapping[str, str]) -> List[str]:
    return sorted(
        key
        for key in environment
        if key in _FORBIDDEN_ENVIRONMENT_EXACT
        or any(key.startswith(prefix) for prefix in _FORBIDDEN_ENVIRONMENT_PREFIXES)
    )


def _validate_request(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REQUEST_KEYS:
        raise ProbeError("probe_request_schema_invalid")
    if (
        value.get("schema_version") != 1
        or value.get("marker") != REQUEST_MARKER
        or not _valid_sha256(value.get("request_id"))
        or not _valid_identity(value.get("bag_identity"))
        or not isinstance(value.get("noetic_prefix"), str)
        or not value.get("noetic_prefix")
        or not _safe_relative(value.get("python_root_relative"))
        or not _valid_identity(value.get("rosbag_module_identity"))
        or not isinstance(value.get("rosbag_decoder_closure"), Mapping)
        or not _valid_identity(value.get("indexer_module_identity"))
        or not _valid_identity(value.get("formal_manifest_identity"))
        or not _valid_identity(value.get("probe_source_identity"))
        or not _valid_identity(value.get("sys_executable_identity"))
        or not _valid_executable_admission(
            value.get("parent_executable_admission")
        )
        or value["parent_executable_admission"].get("target_identity")
        != value.get("sys_executable_identity")
        or not isinstance(value.get("capture_id"), str)
        or not value.get("capture_id")
        or not isinstance(value.get("scene"), str)
        or not value.get("scene")
        or not isinstance(value.get("trusted_system_python_roots"), list)
        or any(
            not isinstance(item, str) or not item
            for item in value.get("trusted_system_python_roots", [])
        )
        or not isinstance(value.get("test_only"), bool)
        or not isinstance(value.get("output_path"), str)
        or not value.get("output_path")
        or type(value.get("max_messages")) is not int
        or value["max_messages"] <= 0
        or type(value.get("max_total_payload_bytes")) is not int
        or value["max_total_payload_bytes"] <= 0
    ):
        raise ProbeError("probe_request_policy_invalid")
    if value["request_id"] != _deterministic_request_id(value):
        raise ProbeError("probe_request_id_mismatch")
    return dict(value)


def _child_failure_marker(
    request_id: Optional[str],
    request_sha256: Optional[str],
    failure: str,
) -> Mapping[str, Any]:
    return {
        "schema_version": 1,
        "marker": CHILD_MARKER,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "status": "FAIL",
        "exit_code": 1,
        "bag_identity": None,
        "noetic_prefix": None,
        "python_root": None,
        "rosbag_module_identity": None,
        "indexer_module_identity": None,
        "formal_manifest_identity": None,
        "probe_source_identity": None,
        "sys_executable_identity": None,
        "child_executable_admission": None,
        "output_identity": None,
        "connection_count": 0,
        "message_count": 0,
        "total_payload_bytes": 0,
        "formal_report_sha256": None,
        "loaded_nonstdlib_module_set_sha256": None,
        "test_only": None,
        "algorithm_validated": False,
        "formal_acceptance": False,
        "not_in_four_scene_denominator": True,
        "forbidden_environment_keys_present": _forbidden_environment_keys(
            os.environ
        ),
        "failures": [failure],
    }


def _child_execute(request_path: Path) -> Tuple[Mapping[str, Any], int]:
    request_id: Optional[str] = None
    request_sha256: Optional[str] = None
    try:
        request_identity = _regular_file_identity(request_path)
        request_sha256 = str(request_identity["sha256"])
        request = _validate_request(
            _strict_json_bytes(Path(request_identity["path"]).read_bytes())
        )
        request_id = request["request_id"]
        forbidden = _forbidden_environment_keys(os.environ)
        if forbidden:
            raise ProbeError("probe_child_environment_not_clean")
        noetic_prefix = Path(request["noetic_prefix"])
        if _path_has_linklike_component(noetic_prefix):
            raise ProbeError("noetic_prefix_linklike")
        prefix_resolved = noetic_prefix.resolve(strict=True)
        if not prefix_resolved.is_dir():
            raise ProbeError("noetic_prefix_invalid")
        python_root = (
            prefix_resolved / request["python_root_relative"]
        ).resolve(strict=True)
        if (
            _path_has_linklike_component(python_root)
            or not python_root.is_dir()
            or not _is_under(python_root, prefix_resolved)
        ):
            raise ProbeError("noetic_python_root_invalid")
        trusted_system_roots = []
        interpreter_root = Path(sys.base_prefix).resolve(strict=True)
        for value in request["trusted_system_python_roots"]:
            candidate = Path(value)
            if (
                _path_has_linklike_component(candidate)
                or not candidate.resolve(strict=True).is_dir()
                or not _is_under(candidate, interpreter_root)
                or any(part.lower() in {"src", "devel", "build"}
                       for part in candidate.parts)
            ):
                raise ProbeError("trusted_system_python_root_invalid")
            trusted_system_roots.append(str(candidate.resolve(strict=True)))
        sys.path[:] = (
            _trusted_stdlib_paths() + trusted_system_roots + [str(python_root)]
        )
        expected_decoder_closure = _validate_decoder_closure(
            request["rosbag_decoder_closure"], python_root
        )
        if (
            expected_decoder_closure.get("rosbag")
            != request["rosbag_module_identity"]
        ):
            raise ProbeError("rosbag_decoder_closure_identity_mismatch")
        probe_source_identity = _regular_file_identity(Path(__file__))
        parent_executable_admission = _admit_executable_entry(
            Path(request["parent_executable_admission"]["entry_path"]),
            request["sys_executable_identity"],
        )
        if parent_executable_admission != request["parent_executable_admission"]:
            raise ProbeError("probe_parent_executable_chain_drift")
        child_executable_admission = _admit_executable_entry(
            Path(sys.executable), request["sys_executable_identity"]
        )
        executable_identity = child_executable_admission["target_identity"]
        if not _identity_matches(
            probe_source_identity, request["probe_source_identity"]
        ):
            raise ProbeError("probe_source_identity_mismatch")
        if not _identity_matches(
            executable_identity, request["sys_executable_identity"]
        ):
            raise ProbeError("probe_sys_executable_identity_mismatch")
        expected_sibling_indexer = Path(__file__).with_name(
            "rosbag1_rgbd_indexer.py"
        ).resolve(strict=True)
        if (
            Path(request["indexer_module_identity"]["path"]).resolve(strict=True)
            != expected_sibling_indexer
        ):
            raise ProbeError("indexer_module_not_probe_sibling")
        bag_identity = _regular_file_identity(Path(request["bag_identity"]["path"]))
        if not _identity_matches(bag_identity, request["bag_identity"]):
            raise ProbeError("bag_identity_mismatch")
        bag_path = Path(bag_identity["path"])
        if bag_path.suffix.lower() != ".bag":
            raise ProbeError("bag_extension_invalid")
        with bag_path.open("rb") as stream:
            if stream.read(len(ROSBAG1_V2_MAGIC)) != ROSBAG1_V2_MAGIC:
                raise ProbeError("rosbag1_v2_magic_invalid")
        rosbag, rosbag_identity = _load_exact_rosbag(
            python_root,
            request["rosbag_module_identity"],
            trusted_system_roots,
        )
        del rosbag
        indexer, indexer_identity = _load_exact_source_module(
            "_limo_ros1_exact_bag_indexer_v1",
            request["indexer_module_identity"],
        )
        manifest_identity = _regular_file_identity(
            Path(request["formal_manifest_identity"]["path"])
        )
        if not _identity_matches(
            manifest_identity, request["formal_manifest_identity"]
        ):
            raise ProbeError("formal_manifest_identity_mismatch")
        try:
            manifest = indexer.load_formal_manifest(
                Path(manifest_identity["path"])
            )
            reader = indexer.Rosbag1Reader(bag_path, diagnostic=True)
            raw_connections, raw_messages = reader.read()
            formal_report = indexer.inspect_records(
                raw_connections,
                raw_messages,
                request["capture_id"],
                request["scene"],
                manifest,
                bag_identity,
                indexer.FORMAL_CAMERA_ONLY_MODE,
            )
        except Exception as error:
            raise ProbeError("formal_indexer_execution_failed") from error
        connections, messages, total_payload_bytes = _serialise_indexer_records(
            raw_connections, raw_messages
        )
        if (
            len(messages) > request["max_messages"]
            or total_payload_bytes > request["max_total_payload_bytes"]
        ):
            raise ProbeError("rosbag_probe_limit_exceeded")
        algorithm_validated = (
            isinstance(formal_report, Mapping)
            and formal_report.get("report_kind")
            == "formal_rgbd_raw_capture_index"
            and formal_report.get("formal_acceptance") is True
            and formal_report.get("delivery_ready") is False
            and formal_report.get("source_capture") == bag_identity
            and formal_report.get("capture_id") == request["capture_id"]
            and formal_report.get("scene") == request["scene"]
        )
        if not algorithm_validated:
            raise ProbeError("formal_indexer_report_invalid")
        formal_report = dict(formal_report)
        formal_report["formal_acceptance"] = False
        formal_report["not_in_four_scene_denominator"] = True
        formal_report["delivery_ready"] = False
        formal_report["test_only"] = request["test_only"]
        formal_report["algorithm_validated"] = True
        formal_report_sha256 = _canonical_sha256(formal_report)
        loaded_module_provenance = _loaded_nonstdlib_provenance(
            [python_root] + [Path(value) for value in trusted_system_roots],
            [Path(__file__), Path(indexer_identity["path"])],
        )
        loaded_module_set_sha256 = _canonical_sha256(
            loaded_module_provenance
        )
        actual_decoder_closure = {
            item["module"]: {
                key: item[key] for key in ("path", "size_bytes", "sha256")
            }
            for item in loaded_module_provenance
            if item["module"] == "rosbag"
            or item["module"].startswith("rosbag.")
        }
        if actual_decoder_closure != expected_decoder_closure:
            raise ProbeError("rosbag_decoder_closure_identity_mismatch")
        post_identities = (
            _regular_file_identity(bag_path),
            _regular_file_identity(Path(indexer_identity["path"])),
            _regular_file_identity(Path(manifest_identity["path"])),
            _regular_file_identity(Path(__file__)),
        )
        if post_identities != (
            bag_identity,
            indexer_identity,
            manifest_identity,
            probe_source_identity,
        ):
            raise ProbeError("probe_bound_artifact_identity_drift")
        if (
            _admit_executable_entry(
                Path(request["parent_executable_admission"]["entry_path"]),
                request["sys_executable_identity"],
            )
            != parent_executable_admission
            or _admit_executable_entry(
                Path(sys.executable), request["sys_executable_identity"]
            )
            != child_executable_admission
        ):
            raise ProbeError("probe_executable_chain_drift")
        output_path = Path(request["output_path"])
        if output_path.exists():
            raise ProbeError("probe_output_exists")
        if _path_has_linklike_component(output_path.parent):
            raise ProbeError("probe_output_parent_linklike")
        artifact = {
            "schema_version": 1,
            "marker": ARTIFACT_MARKER,
            "report_kind": "ros1_isolated_raw_bag_evidence",
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "delivery_ready": False,
            "request_id": request_id,
            "request_sha256": request_sha256,
            "bag_identity": bag_identity,
            "noetic_prefix": str(prefix_resolved),
            "python_root": str(python_root),
            "rosbag_module_identity": rosbag_identity,
            "indexer_module_identity": indexer_identity,
            "formal_manifest_identity": manifest_identity,
            "probe_source_identity": probe_source_identity,
            "sys_executable_identity": executable_identity,
            "parent_executable_admission": parent_executable_admission,
            "child_executable_admission": child_executable_admission,
            "capture_id": request["capture_id"],
            "scene": request["scene"],
            "connections": connections,
            "messages": messages,
            "connection_count": len(connections),
            "message_count": len(messages),
            "total_payload_bytes": total_payload_bytes,
            "formal_report": formal_report,
            "loaded_nonstdlib_module_provenance": loaded_module_provenance,
            "test_only": request["test_only"],
            "algorithm_validated": algorithm_validated,
            "formal_acceptance": False,
            "not_in_four_scene_denominator": True,
        }
        with output_path.open("xb") as stream:
            stream.write(_json_bytes(artifact))
            stream.flush()
            os.fsync(stream.fileno())
        output_identity = _regular_file_identity(output_path)
        marker = {
            "schema_version": 1,
            "marker": CHILD_MARKER,
            "request_id": request_id,
            "request_sha256": request_sha256,
            "status": "PASS",
            "exit_code": 0,
            "bag_identity": bag_identity,
            "noetic_prefix": str(prefix_resolved),
            "python_root": str(python_root),
            "rosbag_module_identity": rosbag_identity,
            "indexer_module_identity": indexer_identity,
            "formal_manifest_identity": manifest_identity,
            "probe_source_identity": probe_source_identity,
            "sys_executable_identity": executable_identity,
            "child_executable_admission": child_executable_admission,
            "output_identity": output_identity,
            "connection_count": len(connections),
            "message_count": len(messages),
            "total_payload_bytes": total_payload_bytes,
            "formal_report_sha256": formal_report_sha256,
            "loaded_nonstdlib_module_set_sha256": loaded_module_set_sha256,
            "test_only": request["test_only"],
            "algorithm_validated": algorithm_validated,
            "formal_acceptance": False,
            "not_in_four_scene_denominator": True,
            "forbidden_environment_keys_present": [],
            "failures": [],
        }
        return marker, 0
    except ProbeError as error:
        return _child_failure_marker(request_id, request_sha256, error.code), 1
    except (
        AttributeError,
        ImportError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        return _child_failure_marker(
            request_id,
            request_sha256,
            "probe_child_unexpected_error:" + type(error).__name__,
        ), 1


def _clean_child_environment(
    environment: Mapping[str, str],
) -> Tuple[Dict[str, str], List[str]]:
    removed = sorted(set(environment) - _CHILD_ENVIRONMENT_ALLOWLIST)
    child = {
        key: value
        for key, value in environment.items()
        if key in _CHILD_ENVIRONMENT_ALLOWLIST
    }
    return child, removed


def _parse_single_child_marker(stdout: str) -> Mapping[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ProbeError("probe_child_marker_count_invalid")
    try:
        marker = _strict_json_bytes(lines[0].encode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ProbeError("probe_child_marker_invalid_json") from error
    if not isinstance(marker, Mapping) or set(marker) != _CHILD_MARKER_KEYS:
        raise ProbeError("probe_child_marker_schema_invalid")
    return marker


def _validate_child_result(
    completed: subprocess.CompletedProcess,
    request_identity: Mapping[str, Any],
    request: Mapping[str, Any],
    expected_bag_identity: Mapping[str, Any],
    expected_rosbag_identity: Mapping[str, Any],
    expected_indexer_identity: Mapping[str, Any],
    expected_manifest_identity: Mapping[str, Any],
    expected_probe_identity: Mapping[str, Any],
    expected_executable_identity: Mapping[str, Any],
    output_path: Path,
) -> Mapping[str, Any]:
    failures: List[str] = []
    marker: Optional[Mapping[str, Any]] = None
    try:
        marker = _parse_single_child_marker(completed.stdout or "")
    except ProbeError as error:
        failures.append(error.code)
    if completed.returncode != 0:
        failures.append("probe_child_exit_nonzero")
    if completed.stderr:
        failures.append("probe_child_stderr_not_empty")
    output_identity = None
    artifact = None
    if output_path.exists():
        try:
            output_identity = _regular_file_identity(output_path)
            artifact = _strict_json_bytes(output_path.read_bytes())
        except (
            ProbeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            OSError,
        ):
            failures.append("probe_output_invalid")
    else:
        failures.append("probe_output_missing")
    if marker is not None:
        if (
            marker.get("schema_version") != 1
            or marker.get("marker") != CHILD_MARKER
            or marker.get("request_id") != request.get("request_id")
            or marker.get("request_sha256") != request_identity.get("sha256")
            or marker.get("status") != "PASS"
            or marker.get("exit_code") != 0
            or marker.get("noetic_prefix")
            != str(Path(request["noetic_prefix"]).resolve(strict=True))
            or marker.get("python_root") != str(
                (
                    Path(request["noetic_prefix"])
                    / request["python_root_relative"]
                ).resolve(strict=True)
            )
            or marker.get("test_only") is not request["test_only"]
            or marker.get("algorithm_validated") is not True
            or marker.get("formal_acceptance") is not False
            or marker.get("not_in_four_scene_denominator") is not True
            or marker.get("failures") != []
            or marker.get("forbidden_environment_keys_present") != []
            or not _valid_executable_admission(
                marker.get("child_executable_admission")
            )
            or marker["child_executable_admission"].get("target_identity")
            != expected_executable_identity
            or marker["child_executable_admission"].get("entry_path")
            != expected_executable_identity.get("path")
        ):
            failures.append("probe_child_marker_policy_invalid")
        if marker.get("bag_identity") != expected_bag_identity:
            failures.append("probe_child_bag_identity_mismatch")
        if marker.get("rosbag_module_identity") != expected_rosbag_identity:
            failures.append("probe_child_rosbag_identity_mismatch")
        if marker.get("indexer_module_identity") != expected_indexer_identity:
            failures.append("probe_child_indexer_identity_mismatch")
        if marker.get("formal_manifest_identity") != expected_manifest_identity:
            failures.append("probe_child_manifest_identity_mismatch")
        if marker.get("probe_source_identity") != expected_probe_identity:
            failures.append("probe_child_source_identity_mismatch")
        if marker.get("sys_executable_identity") != expected_executable_identity:
            failures.append("probe_child_executable_identity_mismatch")
        if marker.get("output_identity") != output_identity:
            failures.append("probe_child_output_identity_mismatch")
    if not isinstance(artifact, Mapping) or set(artifact) != _ARTIFACT_KEYS:
        failures.append("probe_output_schema_invalid")
    elif (
        artifact.get("schema_version") != 1
        or artifact.get("marker") != ARTIFACT_MARKER
        or artifact.get("report_kind") != "ros1_isolated_raw_bag_evidence"
        or artifact.get("read_only") is not True
        or artifact.get("authorizes_motion") is not False
        or artifact.get("publishes_ros_messages") is not False
        or artifact.get("delivery_ready") is not False
        or artifact.get("request_id") != request.get("request_id")
        or artifact.get("request_sha256") != request_identity.get("sha256")
        or artifact.get("bag_identity") != expected_bag_identity
        or artifact.get("rosbag_module_identity") != expected_rosbag_identity
        or artifact.get("indexer_module_identity") != expected_indexer_identity
        or artifact.get("formal_manifest_identity") != expected_manifest_identity
        or artifact.get("probe_source_identity") != expected_probe_identity
        or artifact.get("sys_executable_identity")
        != expected_executable_identity
        or artifact.get("parent_executable_admission")
        != request.get("parent_executable_admission")
        or artifact.get("child_executable_admission")
        != (
            marker.get("child_executable_admission")
            if isinstance(marker, Mapping) else None
        )
        or not isinstance(artifact.get("connections"), list)
        or not isinstance(artifact.get("messages"), list)
        or artifact.get("connection_count") != len(artifact.get("connections", []))
        or artifact.get("message_count") != len(artifact.get("messages", []))
        or not isinstance(artifact.get("formal_report"), Mapping)
        or not isinstance(
            artifact.get("loaded_nonstdlib_module_provenance"), list
        )
    ):
        failures.append("probe_output_policy_invalid")
    elif isinstance(artifact, Mapping):
        try:
            _validate_artifact_semantics(artifact, request)
        except ProbeError as error:
            failures.append(error.code)
    if marker is not None and isinstance(artifact, Mapping):
        for key in ("connection_count", "message_count", "total_payload_bytes"):
            if marker.get(key) != artifact.get(key):
                failures.append("probe_child_output_count_mismatch")
                break
        if marker.get("formal_report_sha256") != _canonical_sha256(
            artifact.get("formal_report")
        ):
            failures.append("probe_child_formal_report_identity_mismatch")
        if marker.get(
            "loaded_nonstdlib_module_set_sha256"
        ) != _canonical_sha256(
            artifact.get("loaded_nonstdlib_module_provenance")
        ):
            failures.append("probe_child_module_set_identity_mismatch")
    return {
        "validated_pass": not failures,
        "marker": marker,
        "output_identity": output_identity,
        "artifact": artifact,
        "failures": sorted(set(failures)),
    }


def run_isolated_rosbag_probe(
    bag_path: Path,
    expected_bag_identity: Mapping[str, Any],
    noetic_prefix: Path,
    expected_rosbag_module_identity: Mapping[str, Any],
    expected_rosbag_decoder_closure: Mapping[str, Mapping[str, Any]],
    expected_indexer_module_identity: Mapping[str, Any],
    formal_manifest_path: Path,
    expected_formal_manifest_identity: Mapping[str, Any],
    expected_probe_source_identity: Mapping[str, Any],
    expected_sys_executable_identity: Mapping[str, Any],
    capture_id: str,
    scene: str,
    output_path: Path,
    *,
    admission_mode: str,
    python_root_relative: str = DEFAULT_PYTHON_ROOT_RELATIVE,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_total_payload_bytes: int = DEFAULT_MAX_TOTAL_PAYLOAD_BYTES,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    trusted_system_python_roots: Sequence[Path] = (),
) -> Mapping[str, Any]:
    """Run one isolated reader probe without mutating the parent environment."""
    failures: List[str] = []
    try:
        actual_bag_identity = _regular_file_identity(Path(bag_path))
        if not _identity_matches(actual_bag_identity, expected_bag_identity):
            raise ProbeError("bag_identity_mismatch")
        prefix = Path(noetic_prefix).resolve(strict=True)
        if _path_has_linklike_component(prefix) or not prefix.is_dir():
            raise ProbeError("noetic_prefix_invalid")
        if not _safe_relative(python_root_relative):
            raise ProbeError("noetic_python_root_invalid")
        python_root = (prefix / python_root_relative).resolve(strict=True)
        if not python_root.is_dir() or not _is_under(python_root, prefix):
            raise ProbeError("noetic_python_root_invalid")
        actual_rosbag_identity = _regular_file_identity(
            Path(expected_rosbag_module_identity.get("path", ""))
        )
        if (
            not _identity_matches(
                actual_rosbag_identity, expected_rosbag_module_identity
            )
            or not _is_under(Path(actual_rosbag_identity["path"]), python_root)
        ):
            raise ProbeError("rosbag_module_identity_mismatch")
        decoder_closure = _validate_decoder_closure(
            expected_rosbag_decoder_closure, python_root
        )
        if decoder_closure.get("rosbag") != actual_rosbag_identity:
            raise ProbeError("rosbag_decoder_closure_identity_mismatch")
        indexer_module_path = Path(__file__).with_name("rosbag1_rgbd_indexer.py")
        actual_indexer_identity = _regular_file_identity(indexer_module_path)
        if not _identity_matches(
            actual_indexer_identity, expected_indexer_module_identity
        ):
            raise ProbeError("indexer_module_identity_mismatch")
        actual_manifest_identity = _regular_file_identity(formal_manifest_path)
        if not _identity_matches(
            actual_manifest_identity, expected_formal_manifest_identity
        ):
            raise ProbeError("formal_manifest_identity_mismatch")
        probe_source_identity = _regular_file_identity(Path(__file__))
        parent_executable_admission = _admit_executable_entry(
            Path(sys.executable), expected_sys_executable_identity
        )
        executable_identity = parent_executable_admission["target_identity"]
        if not _identity_matches(
            probe_source_identity, expected_probe_source_identity
        ):
            raise ProbeError("probe_source_identity_mismatch")
        if not _identity_matches(
            executable_identity, expected_sys_executable_identity
        ):
            raise ProbeError("probe_sys_executable_identity_mismatch")
        if not isinstance(capture_id, str) or not capture_id:
            raise ProbeError("capture_id_invalid")
        if not isinstance(scene, str) or not scene:
            raise ProbeError("scene_invalid")
        if admission_mode not in {"production", "test_only"}:
            raise ProbeError("probe_admission_mode_invalid")
        test_only = admission_mode == "test_only"
        trusted_roots = []
        interpreter_root = Path(sys.base_prefix).resolve(strict=True)
        for root in trusted_system_python_roots:
            candidate = Path(root).resolve(strict=True)
            if (
                _path_has_linklike_component(candidate)
                or not candidate.is_dir()
                or not _is_under(candidate, interpreter_root)
                or any(part.lower() in {"src", "devel", "build"}
                       for part in candidate.parts)
            ):
                raise ProbeError("trusted_system_python_root_invalid")
            trusted_roots.append(str(candidate))
        output = Path(output_path)
        if output.exists():
            raise ProbeError("probe_output_exists")
        if not output.parent.is_dir() or _path_has_linklike_component(output.parent):
            raise ProbeError("probe_output_parent_invalid")
        if (
            type(max_messages) is not int
            or max_messages <= 0
            or type(max_total_payload_bytes) is not int
            or max_total_payload_bytes <= 0
            or isinstance(timeout_sec, bool)
            or not isinstance(timeout_sec, (int, float))
            or not math.isfinite(float(timeout_sec))
            or timeout_sec <= 0
        ):
            raise ProbeError("probe_limits_invalid")
        request = {
            "schema_version": 1,
            "marker": REQUEST_MARKER,
            "bag_identity": dict(actual_bag_identity),
            "noetic_prefix": str(prefix),
            "python_root_relative": python_root_relative,
            "rosbag_module_identity": dict(actual_rosbag_identity),
            "rosbag_decoder_closure": {
                name: dict(identity)
                for name, identity in decoder_closure.items()
            },
            "indexer_module_identity": dict(actual_indexer_identity),
            "formal_manifest_identity": dict(actual_manifest_identity),
            "probe_source_identity": dict(probe_source_identity),
            "sys_executable_identity": dict(executable_identity),
            "parent_executable_admission": parent_executable_admission,
            "capture_id": capture_id,
            "scene": scene,
            "trusted_system_python_roots": trusted_roots,
            "test_only": test_only,
            "output_path": str(output.resolve()),
            "max_messages": max_messages,
            "max_total_payload_bytes": max_total_payload_bytes,
        }
        request["request_id"] = _deterministic_request_id(request)
        request_fd, request_name = tempfile.mkstemp(
            prefix="ros1_bag_probe_request_",
            suffix=".json",
            dir=str(output.parent),
        )
        request_path = Path(request_name)
        try:
            with os.fdopen(request_fd, "wb") as stream:
                stream.write(_json_bytes(request))
                stream.flush()
                os.fsync(stream.fileno())
            request_identity = _regular_file_identity(request_path)
            child_environment, removed_keys = _clean_child_environment(os.environ)
            argv = [
                str(executable_identity["path"]),
                "-I",
                "-S",
                "-B",
                str(Path(__file__).resolve()),
                "--child-request",
                str(request_path.resolve()),
            ]
            parent_environment_snapshot = dict(os.environ)
            parent_path_snapshot = tuple(sys.path)
            parent_meta_path_snapshot = tuple(sys.meta_path)
            parent_rosbag_snapshot = sys.modules.get("rosbag")
            child_execution_failures: List[str] = []
            try:
                completed = subprocess.run(
                    argv,
                    cwd=str(output.parent.resolve()),
                    env=child_environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    timeout=float(timeout_sec),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                child_execution_failures.append("probe_child_timeout")
                completed = subprocess.CompletedProcess(
                    argv, returncode=124, stdout="", stderr=""
                )
            except OSError:
                child_execution_failures.append("probe_child_spawn_failed")
                completed = subprocess.CompletedProcess(
                    argv, returncode=127, stdout="", stderr=""
                )
            parent_environment_restored = (
                dict(os.environ) == parent_environment_snapshot
                and tuple(sys.path) == parent_path_snapshot
                and tuple(sys.meta_path) == parent_meta_path_snapshot
                and sys.modules.get("rosbag") is parent_rosbag_snapshot
            )
            validation = _validate_child_result(
                completed,
                request_identity,
                request,
                actual_bag_identity,
                actual_rosbag_identity,
                actual_indexer_identity,
                actual_manifest_identity,
                probe_source_identity,
                executable_identity,
                output,
            )
            post_identity_failures = []
            for expected in (
                actual_bag_identity,
                actual_rosbag_identity,
                actual_indexer_identity,
                actual_manifest_identity,
                probe_source_identity,
                executable_identity,
            ):
                try:
                    if _regular_file_identity(Path(expected["path"])) != expected:
                        post_identity_failures.append(
                            "probe_parent_bound_artifact_identity_drift"
                        )
                except ProbeError:
                    post_identity_failures.append(
                        "probe_parent_bound_artifact_identity_drift"
                    )
            try:
                if _admit_executable_entry(
                    Path(parent_executable_admission["entry_path"]),
                    executable_identity,
                ) != parent_executable_admission:
                    post_identity_failures.append(
                        "probe_parent_executable_chain_drift"
                    )
            except ProbeError:
                post_identity_failures.append(
                    "probe_parent_executable_chain_drift"
                )
            try:
                if _validate_decoder_closure(
                    decoder_closure, python_root
                ) != decoder_closure:
                    post_identity_failures.append(
                        "probe_parent_decoder_closure_identity_drift"
                    )
            except ProbeError:
                post_identity_failures.append(
                    "probe_parent_decoder_closure_identity_drift"
                )
            artifact = validation.get("artifact")
            return {
                "schema_version": 1,
                "gate_id": GATE_ID,
                "read_only": True,
                "authorizes_motion": False,
                "publishes_ros_messages": False,
                "delivery_ready": False,
                "validated_pass": (
                    validation["validated_pass"]
                    and parent_environment_restored
                    and not post_identity_failures
                    and not test_only
                ),
                "algorithm_validated": (
                    validation["validated_pass"]
                    and parent_environment_restored
                    and not post_identity_failures
                ),
                "test_only": test_only,
                "formal_acceptance": False,
                "not_in_four_scene_denominator": True,
                "argv": argv,
                "environment_removed_keys": removed_keys,
                "request_identity": request_identity,
                "bag_identity": actual_bag_identity,
                "rosbag_module_identity": actual_rosbag_identity,
                "indexer_module_identity": actual_indexer_identity,
                "formal_manifest_identity": actual_manifest_identity,
                "probe_source_identity": probe_source_identity,
                "sys_executable_identity": executable_identity,
                "parent_executable_admission": parent_executable_admission,
                "child_executable_admission": (
                    validation.get("marker", {}).get(
                        "child_executable_admission"
                    )
                    if isinstance(validation.get("marker"), Mapping)
                    else None
                ),
                "parent_environment_restored": parent_environment_restored,
                "child_marker": validation.get("marker"),
                "output_identity": validation.get("output_identity"),
                "connection_count": (
                    artifact.get("connection_count", 0)
                    if isinstance(artifact, Mapping)
                    else 0
                ),
                "message_count": (
                    artifact.get("message_count", 0)
                    if isinstance(artifact, Mapping)
                    else 0
                ),
                "total_payload_bytes": (
                    artifact.get("total_payload_bytes", 0)
                    if isinstance(artifact, Mapping)
                    else 0
                ),
                "failures": sorted(set(
                    validation["failures"]
                    + child_execution_failures
                    + post_identity_failures
                    + ([] if parent_environment_restored else [
                        "probe_parent_environment_not_restored"])
                )),
            }
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass
    except ProbeError as error:
        failures.append(error.code)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append("probe_parent_input_invalid:" + type(error).__name__)
    return {
        "schema_version": 1,
        "gate_id": GATE_ID,
        "read_only": True,
        "authorizes_motion": False,
        "publishes_ros_messages": False,
        "delivery_ready": False,
        "validated_pass": False,
        "algorithm_validated": False,
        "test_only": True,
        "formal_acceptance": False,
        "not_in_four_scene_denominator": True,
        "argv": [],
        "environment_removed_keys": [],
        "request_identity": None,
        "bag_identity": None,
        "rosbag_module_identity": None,
        "indexer_module_identity": None,
        "formal_manifest_identity": None,
        "probe_source_identity": None,
        "sys_executable_identity": None,
        "parent_executable_admission": None,
        "child_executable_admission": None,
        "parent_environment_restored": True,
        "child_marker": None,
        "output_identity": None,
        "connection_count": 0,
        "message_count": 0,
        "total_payload_bytes": 0,
        "failures": sorted(set(failures)),
    }


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--child-request", type=Path, required=True)
    return parser.parse_args(args)


def _main(args: Optional[Sequence[str]] = None) -> int:
    parsed = parse_args(args)
    marker, exit_code = _child_execute(parsed.child_request)
    sys.stdout.write(_json_bytes(marker).decode("utf-8"))
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main())
