"""Hold-open identity broker for the exact workspace-PYC inventory.

The broker is a distinct Python process.  It opens every manifest entry once,
marks all descriptors non-inheritable, and answers only authenticated checkpoint
requests over its private standard-input pipe.  It never imports audited
workspace code and never exports raw bytes, descriptors, or its session nonce.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import threading
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_VERSION = "workspace_pyc_identity_broker_result/v1"
EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA = (
    "host_owned_execution_component_bootstrap/v1"
)
EXECUTION_COMPONENT_BOOTSTRAP_SHA256 = (
    "511f43a8b14f5428588c359739bec177c8db4687112be933eff2f2330a75bb1c"
)
BROKER_RELATIVE_PATH = "audit_tools/workspace_pyc_identity_broker_v1.py"
READY_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_READY "
CHECKPOINT_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_CHECKPOINT "
FINAL_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_FINAL "
ERROR_MARKER = "OFFLINE_WORKSPACE_PYC_BROKER_ERROR "
INIT_SCHEMA = "workspace_pyc_identity_broker_init/v1"
COMMAND_SCHEMA = "workspace_pyc_identity_broker_command/v1"
EXPECTED_INVENTORY_COUNT = 18
EXPECTED_INVENTORY_SHA256 = (
    "5dc8444d9821c591b272ee89e6fdc03ad1cdd79bee105f5017621f3e6daa8292"
)
CHECKPOINT_PHASES = (
    "AFTER_PRODUCTION_WRAPPER",
    "AFTER_TEST_CHILD",
)
SAME_SOURCE_STAT_FIELDS = (
    "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
    "st_nlink", "st_uid_if_present", "st_gid_if_present",
    "st_file_attributes_if_present",
)
WINDOWS_CROSS_SOURCE_STAT_FIELDS = (
    "st_dev", "st_ino", "S_IFMT_st_mode", "st_size", "st_mtime_ns",
    "st_nlink", "st_uid_if_present", "st_gid_if_present",
    "st_file_attributes_if_present",
)
POSIX_CROSS_SOURCE_STAT_FIELDS = (
    "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
    "st_nlink", "st_uid", "st_gid", "st_file_attributes_if_present",
)

_SESSION_LOCK = threading.Lock()
_SESSION_STATE = "UNUSED"
_SESSION_THREAD_ID: int | None = None
_FORBIDDEN_ENVIRONMENT_KEYS = (
    "PYTHONHOME", "PYTHONINSPECT", "PYTHONPATH", "PYTHONSTARTUP",
    "PYTHONUSERBASE", "LD_PRELOAD", "LD_LIBRARY_PATH", "ROS_PACKAGE_PATH",
    "ROS_MASTER_URI", "WSLENV", "LIMO_PYC_BROKER_FD",
    "LIMO_PYC_BROKER_TOKEN", "LIMO_PYC_BROKER_NONCE",
)


class BrokerFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BrokerFailure("pyc_broker_json_duplicate_key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise BrokerFailure("pyc_broker_json_nonfinite")


def _strict_json_line(raw: str) -> Any:
    if not raw.endswith("\n"):
        raise BrokerFailure("pyc_broker_command_truncated")
    try:
        value = json.loads(
            raw[:-1], object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
        if raw[:-1].encode("utf-8") != _canonical_json(value):
            raise BrokerFailure("pyc_broker_command_json_invalid")
        return value
    except BrokerFailure:
        raise
    except (UnicodeError, ValueError) as error:
        raise BrokerFailure("pyc_broker_command_json_invalid") from error


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _is_linklike(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in ("", ".", "..") for part in path.parts)
        and path.as_posix() == value
    )


def _claim_session() -> None:
    global _SESSION_STATE, _SESSION_THREAD_ID
    current = threading.get_ident()
    with _SESSION_LOCK:
        if _SESSION_STATE == "RUNNING":
            if _SESSION_THREAD_ID == current:
                raise BrokerFailure("pyc_broker_session_nested_start_forbidden")
            raise BrokerFailure("pyc_broker_session_duplicate_start")
        if _SESSION_STATE != "UNUSED":
            raise BrokerFailure("pyc_broker_session_reuse_after_finalize")
        _SESSION_STATE = "RUNNING"
        _SESSION_THREAD_ID = current


def _require_session_thread() -> None:
    with _SESSION_LOCK:
        if (
            _SESSION_STATE != "RUNNING"
            or _SESSION_THREAD_ID != threading.get_ident()
        ):
            raise BrokerFailure("pyc_broker_command_wrong_thread")


def _finish_session(state: str) -> None:
    global _SESSION_STATE, _SESSION_THREAD_ID
    with _SESSION_LOCK:
        _SESSION_STATE = state
        _SESSION_THREAD_ID = None


def _stat_projection(info: os.stat_result) -> Tuple[Any, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
        getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000)),
        getattr(info, "st_nlink", 1), getattr(info, "st_uid", None),
        getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _cross_source_projection(info: os.stat_result) -> Tuple[Any, ...]:
    mode = stat.S_IFMT(info.st_mode) if os.name == "nt" else info.st_mode
    common = (
        info.st_dev, info.st_ino, mode, info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
    )
    # Windows path and descriptor stat sources can report different permission
    # bits and different ctime semantics for the same dev/inode.  Both remain
    # fully bound in their respective before/after projections; cross-source
    # equivalence uses only the fields that Windows exposes consistently.
    if os.name == "nt":
        return common + (
            getattr(info, "st_nlink", 1), getattr(info, "st_uid", None),
            getattr(info, "st_gid", None),
            getattr(info, "st_file_attributes", None),
        )
    return common + (
        getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000)),
        getattr(info, "st_nlink", 1), getattr(info, "st_uid", None),
        getattr(info, "st_gid", None),
        getattr(info, "st_file_attributes", None),
    )


def _read_fd(descriptor: int) -> Tuple[int, str]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def _validate_workspace(raw: str) -> Path:
    if not Path(raw).is_absolute():
        raise BrokerFailure("pyc_broker_workspace_invalid")
    lexical = Path(os.path.abspath(raw))
    before = os.lstat(str(lexical))
    if _is_linklike(before) or not stat.S_ISDIR(before.st_mode):
        raise BrokerFailure("pyc_broker_workspace_invalid")
    resolved = lexical.resolve(strict=True)
    if resolved != lexical:
        raise BrokerFailure("pyc_broker_workspace_invalid")
    if Path.cwd().resolve(strict=True) != resolved:
        raise BrokerFailure("pyc_broker_cwd_invalid")
    return resolved


def _validate_process_contract() -> None:
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise BrokerFailure("pyc_broker_process_contract_invalid")
    if any(
        os.environ.get(key) not in (None, "")
        for key in _FORBIDDEN_ENVIRONMENT_KEYS
    ):
        raise BrokerFailure("pyc_broker_process_contract_invalid")


def _validate_execution_binding(workspace: Path) -> Dict[str, Any]:
    value = globals().get("__execution_component_binding__")
    required = {
        "schema_version", "component_kind", "path", "size_bytes",
        "sha256", "bootstrap_sha256",
    }
    if value is None:
        raise BrokerFailure("pyc_broker_execution_binding_missing")
    if not isinstance(value, dict) or set(value) != required:
        raise BrokerFailure("pyc_broker_execution_binding_schema_invalid")
    if value.get("schema_version") != EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA:
        raise BrokerFailure("pyc_broker_execution_binding_schema_invalid")
    if value.get("component_kind") != "broker":
        raise BrokerFailure("pyc_broker_execution_binding_kind_invalid")
    if value.get("path") != BROKER_RELATIVE_PATH:
        raise BrokerFailure("pyc_broker_execution_binding_path_invalid")
    if value.get("bootstrap_sha256") != EXECUTION_COMPONENT_BOOTSTRAP_SHA256:
        raise BrokerFailure("pyc_broker_execution_binding_bootstrap_invalid")
    if (
        type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
        or not isinstance(value.get("sha256"), str)
        or len(value["sha256"]) != 64
        or any(character not in "0123456789abcdef"
               for character in value["sha256"])
    ):
        raise BrokerFailure("pyc_broker_execution_binding_identity_invalid")
    path = _path_for(workspace, BROKER_RELATIVE_PATH)
    if Path(__file__).resolve(strict=True) != path.resolve(strict=True):
        raise BrokerFailure("pyc_broker_execution_binding_origin_invalid")
    before = os.lstat(str(path))
    if (
        _is_linklike(before) or not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_nlink", 1) != 1
    ):
        raise BrokerFailure("pyc_broker_execution_binding_live_drift")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise BrokerFailure("pyc_broker_execution_binding_live_drift") from error
    try:
        os.set_inheritable(descriptor, False)
        opened_before = os.fstat(descriptor)
        if (
            os.get_inheritable(descriptor)
            or not stat.S_ISREG(opened_before.st_mode)
            or getattr(opened_before, "st_nlink", 1) != 1
            or _cross_source_projection(before)
            != _cross_source_projection(opened_before)
        ):
            raise BrokerFailure("pyc_broker_execution_binding_live_drift")
        size, digest = _read_fd(descriptor)
        opened_after = os.fstat(descriptor)
        if _stat_projection(opened_before) != _stat_projection(opened_after):
            raise BrokerFailure("pyc_broker_execution_binding_live_drift")
    finally:
        os.close(descriptor)
    after = os.lstat(str(path))
    if (
        _is_linklike(after) or not stat.S_ISREG(after.st_mode)
        or getattr(after, "st_nlink", 1) != 1
        or _stat_projection(before) != _stat_projection(after)
        or _cross_source_projection(opened_after)
        != _cross_source_projection(after)
        or size != before.st_size or size != opened_before.st_size
        or size != opened_after.st_size or size != after.st_size
    ):
        raise BrokerFailure("pyc_broker_execution_binding_live_drift")
    if size != value["size_bytes"] or digest != value["sha256"]:
        raise BrokerFailure("pyc_broker_execution_binding_identity_mismatch")
    return dict(value)


def _manifest(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise BrokerFailure("pyc_broker_manifest_missing")
    if len(value) < EXPECTED_INVENTORY_COUNT:
        raise BrokerFailure("pyc_broker_manifest_missing")
    if len(value) > EXPECTED_INVENTORY_COUNT:
        raise BrokerFailure("pyc_broker_manifest_extra")
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path", "size_bytes", "sha256",
        }:
            raise BrokerFailure("pyc_broker_manifest_missing")
        path = item.get("path")
        if (
            not _safe_relative(path)
            or not path.casefold().endswith(".pyc")
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] < 0
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["sha256"])
        ):
            raise BrokerFailure("pyc_broker_manifest_missing")
        if path in seen:
            raise BrokerFailure("pyc_broker_manifest_duplicate")
        seen.add(path)
        result.append(dict(item))
    if result != sorted(result, key=lambda item: item["path"]):
        raise BrokerFailure("pyc_broker_manifest_order_mismatch")
    return result


def _path_for(workspace: Path, relative: str) -> Path:
    current = workspace
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(str(current))
        except OSError as error:
            raise BrokerFailure("pyc_broker_manifest_missing") from error
        if _is_linklike(info):
            if index + 1 == len(parts):
                raise BrokerFailure("pyc_broker_file_linklike")
            raise BrokerFailure("pyc_broker_parent_chain_linklike")
        if index + 1 < len(parts) and not stat.S_ISDIR(info.st_mode):
            raise BrokerFailure("pyc_broker_parent_chain_not_directory")
    return current


def _open_entry(workspace: Path, expected: Mapping[str, Any]) -> Dict[str, Any]:
    path = _path_for(workspace, expected["path"])
    before = os.lstat(str(path))
    if _is_linklike(before):
        raise BrokerFailure("pyc_broker_file_linklike")
    if not stat.S_ISREG(before.st_mode):
        raise BrokerFailure("pyc_broker_file_not_regular")
    if getattr(before, "st_nlink", 1) != 1:
        raise BrokerFailure("pyc_broker_file_hardlink_rejected")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise BrokerFailure("pyc_broker_file_open_failed") from error
    try:
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise BrokerFailure("pyc_broker_file_drift")
        opened_before = os.fstat(descriptor)
        if not stat.S_ISREG(opened_before.st_mode):
            raise BrokerFailure("pyc_broker_file_not_regular")
        if getattr(opened_before, "st_nlink", 1) != 1:
            raise BrokerFailure("pyc_broker_file_hardlink_rejected")
        if _cross_source_projection(opened_before) != _cross_source_projection(before):
            raise BrokerFailure("pyc_broker_path_fd_identity_mismatch")
        try:
            size, digest = _read_fd(descriptor)
        except OSError as error:
            raise BrokerFailure("pyc_broker_fd_closed_before_finalize") from error
        opened_after = os.fstat(descriptor)
        after = os.lstat(str(path))
        if _stat_projection(opened_before) != _stat_projection(opened_after):
            raise BrokerFailure("pyc_broker_file_drift")
        if _stat_projection(before) != _stat_projection(after):
            raise BrokerFailure("pyc_broker_file_drift")
        if _cross_source_projection(opened_after) != _cross_source_projection(after):
            raise BrokerFailure("pyc_broker_path_fd_identity_mismatch")
        if size != expected["size_bytes"]:
            raise BrokerFailure("pyc_broker_size_mismatch")
        if digest != expected["sha256"]:
            raise BrokerFailure("pyc_broker_sha256_mismatch")
        return {
            "path": path,
            "relative": expected["path"],
            "descriptor": descriptor,
            "fd_state": opened_after,
            "path_state": after,
            "identity": {
                "path": expected["path"],
                "size_bytes": size,
                "sha256": digest,
                "regular_file": True,
                "non_linklike": True,
                "nlink": 1,
                "fd_inheritable": os.get_inheritable(descriptor),
            },
        }
    except BaseException:
        os.close(descriptor)
        raise


def _checkpoint(entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    identities: List[Dict[str, Any]] = []
    for entry in entries:
        descriptor = entry["descriptor"]
        try:
            if os.get_inheritable(descriptor):
                raise BrokerFailure("pyc_broker_file_drift")
            fd_before = os.fstat(descriptor)
        except BrokerFailure:
            raise
        except OSError as error:
            raise BrokerFailure("pyc_broker_fd_closed_before_finalize") from error
        try:
            path_before = os.lstat(str(entry["path"]))
        except OSError as error:
            raise BrokerFailure("pyc_broker_file_drift") from error
        if (
            _is_linklike(path_before)
            or not stat.S_ISREG(path_before.st_mode)
            or getattr(path_before, "st_nlink", 1) != 1
        ):
            raise BrokerFailure("pyc_broker_file_drift")
        if _stat_projection(fd_before) != _stat_projection(entry["fd_state"]):
            raise BrokerFailure("pyc_broker_file_drift")
        if _stat_projection(path_before) != _stat_projection(entry["path_state"]):
            raise BrokerFailure("pyc_broker_file_drift")
        size, digest = _read_fd(descriptor)
        try:
            fd_after = os.fstat(descriptor)
        except OSError as error:
            raise BrokerFailure("pyc_broker_fd_closed_before_finalize") from error
        try:
            path_after = os.lstat(str(entry["path"]))
        except OSError as error:
            raise BrokerFailure("pyc_broker_file_drift") from error
        if _stat_projection(fd_before) != _stat_projection(fd_after):
            raise BrokerFailure("pyc_broker_file_drift")
        if _stat_projection(path_before) != _stat_projection(path_after):
            raise BrokerFailure("pyc_broker_file_drift")
        if _cross_source_projection(fd_after) != _cross_source_projection(path_after):
            raise BrokerFailure("pyc_broker_path_fd_identity_mismatch")
        identity = entry["identity"]
        if size != identity["size_bytes"] or digest != identity["sha256"]:
            raise BrokerFailure("pyc_broker_file_drift")
        identities.append(dict(identity))
    return identities


def _event(
    event: str, record_id: str, checkpoint_index: int, phase: str,
    manifest_digest: str, nonce_digest: str,
    identities: Sequence[Mapping[str, Any]], nonce_key: bytes,
    descriptor_count: int, descriptors_closed: bool, nonce_invalidated: bool,
    broker_execution_binding: Mapping[str, Any],
) -> Dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "record_id": record_id,
        "checkpoint_index": checkpoint_index,
        "phase": phase,
        "inventory_sha256": manifest_digest,
        "nonce_sha256": nonce_digest,
        "identities": [dict(item) for item in identities],
        "raw_bytes_exported": False,
        "file_descriptors_exported": False,
        "descriptor_count": descriptor_count,
        "descriptors_closed": descriptors_closed,
        "nonce_invalidated": nonce_invalidated,
        "broker_execution_binding": dict(broker_execution_binding),
    }
    payload["hmac_sha256"] = hmac.new(
        nonce_key, _canonical_json(payload), hashlib.sha256,
    ).hexdigest()
    return payload


def _emit(marker: str, payload: Mapping[str, Any]) -> None:
    sys.stdout.write(marker + _canonical_json(payload).decode("utf-8") + "\n")
    sys.stdout.flush()


def run_session(
    workspace: Path, record_id: str,
    broker_execution_binding: Mapping[str, Any],
) -> int:
    _claim_session()
    completed = False
    nonce_key = bytearray()
    try:
        raw_init = sys.stdin.readline()
        if raw_init == "":
            raise BrokerFailure("pyc_broker_early_exit")
        initial = _strict_json_line(raw_init)
        if not isinstance(initial, dict) or set(initial) != {
            "schema_version", "record_id", "nonce", "inventory",
            "inventory_sha256",
        }:
            raise BrokerFailure("pyc_broker_manifest_missing")
        if initial.get("schema_version") != INIT_SCHEMA:
            raise BrokerFailure("pyc_broker_manifest_missing")
        if initial.get("record_id") != record_id:
            raise BrokerFailure("pyc_broker_record_scope_invalid")
        nonce = initial.get("nonce")
        if (
            not isinstance(nonce, str) or len(nonce) != 64
            or any(character not in "0123456789abcdef" for character in nonce)
        ):
            raise BrokerFailure("pyc_broker_nonce_mismatch")
        manifest = _manifest(initial.get("inventory"))
        manifest_digest = _canonical_sha256(manifest)
        if initial.get("inventory_sha256") != manifest_digest:
            raise BrokerFailure("pyc_broker_manifest_digest_mismatch")
        if manifest_digest != EXPECTED_INVENTORY_SHA256:
            raise BrokerFailure("pyc_broker_manifest_digest_mismatch")
        nonce_key.extend(bytes.fromhex(nonce))
        nonce_digest = hashlib.sha256(nonce_key).hexdigest()
        del initial
        del raw_init
    except BaseException:
        for index in range(len(nonce_key)):
            nonce_key[index] = 0
        _finish_session("FAILED")
        raise
    entries: List[Mapping[str, Any]] = []
    try:
        _require_session_thread()
        for item in manifest:
            entries.append(_open_entry(workspace, item))
        identities = _checkpoint(entries)
        _emit(READY_MARKER, _event(
            "READY", record_id, 0, "READY", manifest_digest, nonce_digest,
            identities, bytes(nonce_key), len(entries), False, False,
            broker_execution_binding,
        ))
        checkpoint_index = 0
        while True:
            _require_session_thread()
            raw = sys.stdin.readline()
            if raw == "":
                raise BrokerFailure("pyc_broker_finalize_missing")
            command = _strict_json_line(raw)
            if not isinstance(command, dict) or set(command) != {
                "schema_version", "record_id", "nonce", "command", "index",
                "phase",
            }:
                raise BrokerFailure("pyc_broker_unexpected_command")
            if command.get("schema_version") != COMMAND_SCHEMA:
                raise BrokerFailure("pyc_broker_unexpected_command")
            if command.get("record_id") != record_id:
                raise BrokerFailure("pyc_broker_record_scope_invalid")
            if command.get("command") not in ("checkpoint", "finalize"):
                raise BrokerFailure("pyc_broker_unexpected_command")
            command_nonce = command.get("nonce")
            if (
                not isinstance(command_nonce, str)
                or not hmac.compare_digest(command_nonce, nonce)
            ):
                raise BrokerFailure("pyc_broker_nonce_mismatch")
            expected_index = checkpoint_index + 1
            if command.get("index") != expected_index:
                raise BrokerFailure("pyc_broker_checkpoint_order_invalid")
            phase = command.get("phase")
            if not isinstance(phase, str) or not phase:
                raise BrokerFailure("pyc_broker_unexpected_command")
            if expected_index <= len(CHECKPOINT_PHASES):
                if (
                    command.get("command") != "checkpoint"
                    or phase != CHECKPOINT_PHASES[expected_index - 1]
                ):
                    raise BrokerFailure("pyc_broker_checkpoint_order_invalid")
            elif expected_index == len(CHECKPOINT_PHASES) + 1:
                if command.get("command") != "finalize" or phase != "FINAL":
                    raise BrokerFailure("pyc_broker_checkpoint_order_invalid")
            else:
                raise BrokerFailure("pyc_broker_session_reuse_after_finalize")
            checkpoint_index = expected_index
            identities = _checkpoint(entries)
            if command.get("command") == "checkpoint":
                _emit(CHECKPOINT_MARKER, _event(
                    "CHECKPOINT", record_id, checkpoint_index, phase,
                    manifest_digest, nonce_digest, identities, bytes(nonce_key),
                    len(entries), False, False,
                    broker_execution_binding,
                ))
            elif command.get("command") == "finalize":
                close_failed = False
                for entry in entries:
                    descriptor = entry["descriptor"]
                    try:
                        os.close(descriptor)
                    except OSError:
                        close_failed = True
                        continue
                    try:
                        os.fstat(descriptor)
                    except OSError:
                        pass
                    else:
                        close_failed = True
                entries = []
                if close_failed:
                    raise BrokerFailure("pyc_broker_close_incomplete")
                final_event = _event(
                    "FINAL", record_id, checkpoint_index, "FINAL",
                    manifest_digest, nonce_digest, identities, bytes(nonce_key),
                    0, True, True,
                    broker_execution_binding,
                )
                for index in range(len(nonce_key)):
                    nonce_key[index] = 0
                nonce = ""
                trailing = sys.stdin.readline()
                if trailing != "":
                    raise BrokerFailure("pyc_broker_session_reuse_after_finalize")
                _emit(FINAL_MARKER, final_event)
                completed = True
                break
        return 0
    finally:
        for entry in entries:
            try:
                os.close(entry["descriptor"])
            except OSError:
                pass
        for index in range(len(nonce_key)):
            nonce_key[index] = 0
        _finish_session("FINALIZED" if completed else "FAILED")


def _parse_argv(argv: Sequence[str] | None) -> Tuple[str, str]:
    raw = list(sys.argv[1:] if argv is None else argv)
    if (
        len(raw) != 6
        or raw[0:2] != ["--mode", "hold-open-v1"]
        or raw[2] != "--workspace"
        or raw[4] != "--record-id"
    ):
        raise BrokerFailure("pyc_broker_record_scope_invalid")
    return raw[3], raw[5]


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _validate_process_contract()
        raw_workspace, record_id = _parse_argv(argv)
        workspace = _validate_workspace(raw_workspace)
        broker_execution_binding = _validate_execution_binding(workspace)
        if (
            not record_id
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in record_id
            )
        ):
            raise BrokerFailure("pyc_broker_record_scope_invalid")
        return run_session(workspace, record_id, broker_execution_binding)
    except BrokerFailure as error:
        _emit(ERROR_MARKER, {
            "schema_version": SCHEMA_VERSION,
            "validated_pass": False,
            "failure_code": error.code,
            "raw_bytes_exported": False,
            "file_descriptors_exported": False,
        })
        return 2
    except BaseException:
        _emit(ERROR_MARKER, {
            "schema_version": SCHEMA_VERSION,
            "validated_pass": False,
            "failure_code": "pyc_broker_unhandled_failure",
            "raw_bytes_exported": False,
            "file_descriptors_exported": False,
        })
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BROKER_RELATIVE_PATH", "BrokerFailure", "CHECKPOINT_MARKER",
    "CHECKPOINT_PHASES", "COMMAND_SCHEMA",
    "ERROR_MARKER", "EXPECTED_INVENTORY_COUNT", "EXPECTED_INVENTORY_SHA256",
    "EXECUTION_COMPONENT_BOOTSTRAP_SCHEMA",
    "EXECUTION_COMPONENT_BOOTSTRAP_SHA256",
    "FINAL_MARKER", "INIT_SCHEMA", "POSIX_CROSS_SOURCE_STAT_FIELDS",
    "READY_MARKER", "SAME_SOURCE_STAT_FIELDS", "SCHEMA_VERSION",
    "WINDOWS_CROSS_SOURCE_STAT_FIELDS", "main", "run_session",
]
