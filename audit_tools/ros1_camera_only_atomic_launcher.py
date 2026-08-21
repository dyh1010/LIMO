"""Atomically bind the audited DaBai bytes to a future roslaunch exec.

The ordinary static preflight remains inert.  This separate entry point is the
only documented production path from that preflight to a camera-only launch.
It repeats the host-owned preflight, opens the exact live launch with
``O_NOFOLLOW``, copies the validated bytes to a sealed Linux memfd, and binds
both that immutable launch and the admitted roslaunch script to inherited file
descriptors.  A separately admitted versioned Python target executes a fixed
``-I -S -B`` host bootstrap which runs roslaunch only from its open descriptor.

No code in this module is exercised against ROS or hardware by the offline
tests.  Tests use the private in-process exec seam and verify the immutable
file descriptor and argv without starting an external command.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from importlib.machinery import BuiltinImporter, ExtensionFileLoader, PathFinder
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import types
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

PREFLIGHT_SOURCE_IDENTITY: Mapping[str, Any] = {
    "path": "audit_tools/ros1_camera_only_field_preflight.py",
    "size_bytes": 44701,
    "sha256": "c355d630d358755f8f5870c2a79fe5dba3906b0dd31b7c2e216762c7bcffc026",
}
RUNTIME_ADMISSION_SOURCE_IDENTITY: Mapping[str, Any] = {
    "path": "audit_tools/ros1_camera_runtime_install_admission.py",
    "size_bytes": 93681,
    "sha256": "4c7c90ef7d452717599d7b9b8b7d47b138ba9fe50f855cb58dfd1f8f73b76680",
}


def _early_snapshot(value: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        int(value.st_dev), int(value.st_ino), int(value.st_mode),
        int(value.st_size), int(value.st_mtime_ns),
    )


def _load_exact_preflight_module():
    path = Path(__file__).resolve().with_name(
        "ros1_camera_only_field_preflight.py")
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RuntimeError("preflight_source_linklike_or_nonregular")
    if path.resolve(strict=True) != path:
        raise RuntimeError("preflight_source_resolved_path_mismatch")
    raw = path.read_bytes()
    after = path.lstat()
    if _early_snapshot(before) != _early_snapshot(after):
        raise RuntimeError("preflight_source_changed_during_read")
    if (len(raw) != PREFLIGHT_SOURCE_IDENTITY["size_bytes"]
            or hashlib.sha256(raw).hexdigest()
            != PREFLIGHT_SOURCE_IDENTITY["sha256"]):
        raise RuntimeError("preflight_source_identity_mismatch")
    name = "_limo_host_camera_preflight_exact_20260815_v1"
    # Execute the already hashed immutable byte string.  A file-backed loader
    # would reopen the pathname after validation and recreate the TOCTOU gap
    # this launcher is intended to close.
    code = compile(raw, str(path), "exec", dont_inherit=True)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    exec(code, module.__dict__)
    final = path.lstat()
    if _early_snapshot(before) != _early_snapshot(final):
        raise RuntimeError("preflight_source_changed_before_execution_complete")
    if Path(module.__file__).resolve(strict=True) != path:
        raise RuntimeError("preflight_source_loaded_path_mismatch")
    return module


def _load_exact_runtime_admission_module():
    identity = RUNTIME_ADMISSION_SOURCE_IDENTITY
    size_bytes = identity.get("size_bytes")
    sha256 = identity.get("sha256")
    if (type(size_bytes) is not int or size_bytes <= 0
            or not isinstance(sha256, str) or len(sha256) != 64
            or sha256 != sha256.lower()
            or any(item not in "0123456789abcdef" for item in sha256)):
        raise RuntimeError("runtime_admission_source_anchor_unbound")
    path = Path(__file__).resolve().with_name(
        "ros1_camera_runtime_install_admission.py")
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RuntimeError("runtime_admission_source_linklike_or_nonregular")
    if path.resolve(strict=True) != path:
        raise RuntimeError("runtime_admission_source_resolved_path_mismatch")
    raw = path.read_bytes()
    after = path.lstat()
    if _early_snapshot(before) != _early_snapshot(after):
        raise RuntimeError("runtime_admission_source_changed_during_read")
    if len(raw) != size_bytes or hashlib.sha256(raw).hexdigest() != sha256:
        raise RuntimeError("runtime_admission_source_identity_mismatch")
    name = "_limo_host_camera_runtime_admission_exact_20260815_v1"
    code = compile(raw, str(path), "exec", dont_inherit=True)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    exec(code, module.__dict__)
    final = path.lstat()
    if _early_snapshot(before) != _early_snapshot(final):
        raise RuntimeError(
            "runtime_admission_source_changed_before_execution_complete")
    if Path(module.__file__).resolve(strict=True) != path:
        raise RuntimeError("runtime_admission_source_loaded_path_mismatch")
    evaluator = module.__dict__.get(
        "evaluate_camera_runtime_install_admission")
    if not callable(evaluator):
        raise RuntimeError("runtime_admission_evaluator_missing")
    return module


def _load_independent_fcntl():
    """Load fcntl without consulting ambient sys.modules or sys.meta_path."""
    if not sys.platform.startswith("linux"):
        return None
    spec = BuiltinImporter.find_spec("fcntl")
    if spec is None:
        version = "{}.{}".format(
            sys.version_info.major, sys.version_info.minor)
        roots = (
            Path(sys.base_exec_prefix) / "lib" /
            ("python" + version) / "lib-dynload",
            Path(sys.base_prefix) / "lib" /
            ("python" + version) / "lib-dynload",
        )
        for root in roots:
            try:
                candidate_root = root.resolve(strict=True)
            except OSError:
                continue
            candidate = PathFinder.find_spec("fcntl", [str(candidate_root)])
            if (candidate is not None
                    and isinstance(candidate.loader, ExtensionFileLoader)):
                spec = candidate
                break
    if spec is None or spec.loader is None:
        raise RuntimeError("trusted_fcntl_spec_unavailable")
    sentinel = object()
    ambient = sys.modules.pop("fcntl", sentinel)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if ambient is sentinel:
            sys.modules.pop("fcntl", None)
        else:
            sys.modules["fcntl"] = ambient
    return module


def _attest_ambient_fcntl(module) -> Mapping[str, Any]:
    """Reject spoofed pre-import state without executing any ambient callable."""
    if not sys.platform.startswith("linux"):
        return {"present": False, "validated": False}
    ambient = sys.modules.get("fcntl")
    if ambient is None:
        return {"present": False, "validated": True}
    if type(ambient) is not types.ModuleType:
        raise RuntimeError("trusted_fcntl_ambient_identity_mismatch")
    namespace = types.ModuleType.__getattribute__(ambient, "__dict__")
    trusted_namespace = types.ModuleType.__getattribute__(module, "__dict__")
    spec = namespace.get("__spec__")
    trusted_spec = trusted_namespace.get("__spec__")
    if (type(spec) is not type(trusted_spec)
            or spec.name != "fcntl"
            or spec.origin != trusted_spec.origin
            or spec.loader is not trusted_spec.loader
            and type(spec.loader) is not type(trusted_spec.loader)):
        raise RuntimeError("trusted_fcntl_ambient_identity_mismatch")
    function = namespace.get("fcntl")
    if (not isinstance(function, types.BuiltinFunctionType)
            or getattr(function, "__module__", None) != "fcntl"
            or getattr(function, "__name__", None) != "fcntl"):
        raise RuntimeError("trusted_fcntl_ambient_identity_mismatch")
    constant_names = (
        "F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW",
        "F_SEAL_SHRINK", "F_SEAL_SEAL")
    if any(type(namespace.get(name)) is not int
           or namespace[name] != trusted_namespace.get(name)
           for name in constant_names):
        raise RuntimeError("trusted_fcntl_ambient_identity_mismatch")
    return {
        "present": True,
        "validated": True,
        "origin": spec.origin,
        "loader": (
            "{}.{}".format(spec.loader.__module__, spec.loader.__name__)
            if isinstance(spec.loader, type)
            else "{}.{}".format(
                type(spec.loader).__module__, type(spec.loader).__name__)),
        "native_fcntl": True,
    }


def _attest_trusted_fcntl() -> Mapping[str, Any]:
    if not sys.platform.startswith("linux"):
        return {"required": False, "validated": False}
    module = _TRUSTED_FCNTL
    if module is None:
        raise RuntimeError("trusted_fcntl_unavailable")
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    loader = getattr(spec, "loader", None)
    namespace = types.ModuleType.__getattribute__(module, "__dict__")
    function = namespace.get("fcntl")
    if (type(module) is not types.ModuleType
            or not isinstance(function, types.BuiltinFunctionType)
            or getattr(function, "__module__", None) != "fcntl"
            or getattr(function, "__name__", None) != "fcntl"):
        raise RuntimeError("trusted_fcntl_native_function_invalid")
    if not isinstance(origin, str) or not origin:
        raise RuntimeError("trusted_fcntl_origin_invalid")
    loader_name = (
        "{}.{}".format(loader.__module__, loader.__name__)
        if isinstance(loader, type)
        else "{}.{}".format(type(loader).__module__, type(loader).__name__)
        if loader is not None else "")
    if origin in {"built-in", "frozen"}:
        if loader_name not in {
                "_frozen_importlib.BuiltinImporter",
                "_frozen_importlib.FrozenImporter"}:
            raise RuntimeError("trusted_fcntl_loader_invalid")
        return {
            "required": True,
            "validated": True,
            "origin": origin,
            "loader": loader_name,
            "size_bytes": None,
            "sha256": None,
            "native_fcntl": True,
        }
    path = Path(origin)
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("trusted_fcntl_origin_unavailable") from error
    if (not path.is_absolute()
            or resolved != path
            or stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)):
        raise RuntimeError("trusted_fcntl_origin_not_regular")
    trusted_roots = {
        Path(sys.base_prefix).resolve(strict=True),
        Path(sys.base_exec_prefix).resolve(strict=True),
    }
    def within(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False
    if not any(within(resolved, root) for root in trusted_roots):
        raise RuntimeError("trusted_fcntl_origin_outside_stdlib_root")
    if loader_name not in {
            "_frozen_importlib_external.ExtensionFileLoader",
            "_frozen_importlib.BuiltinImporter"}:
        raise RuntimeError("trusted_fcntl_loader_invalid")
    raw = path.read_bytes()
    after = path.lstat()
    if _early_snapshot(before) != _early_snapshot(after):
        raise RuntimeError("trusted_fcntl_origin_changed_during_read")
    return {
        "required": True,
        "validated": True,
        "origin": str(path),
        "loader": loader_name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "native_fcntl": True,
    }


_TRUSTED_FCNTL = _load_independent_fcntl()
AMBIENT_FCNTL_PROVENANCE = _attest_ambient_fcntl(_TRUSTED_FCNTL)
PREFLIGHT = _load_exact_preflight_module()
TRUSTED_FCNTL_PROVENANCE = _attest_trusted_fcntl()

# Snapshot the exact, source-anchored preflight launch path before any private
# unit-test patching.  Admission material must name this same production path;
# a caller cannot select a different Astra launch and rely on the later
# preflight invocation to discover the mismatch indirectly.
ATTESTED_PRODUCTION_VENDOR_LAUNCH_PATH = str(
    PREFLIGHT.PRODUCTION_VENDOR_LAUNCH_PATH)


SCHEMA_VERSION = "ros1_camera_only_atomic_launcher/v1"
MODE = "EXECUTE_AUDITED_CAMERA_ONLY"
CLI_REQUIRED_OPTIONS: Tuple[str, ...] = (
    "--mode",
    "--actual-vendor-launch",
)
ROSLAUNCH_EXECUTABLE = "/opt/ros/noetic/bin/roslaunch"
REQUIRED_SEAL_NAMES = (
    "F_SEAL_WRITE",
    "F_SEAL_GROW",
    "F_SEAL_SHRINK",
    "F_SEAL_SEAL",
)
CAMERA_ONLY_OVERRIDES: Tuple[str, ...] = (
    "camera_name:=camera",
    "serial_number:=CC1WC520183",
    "depth_align:=true",
    "color_depth_synchronization:=true",
    "enable_ir:=false",
    "enable_point_cloud:=false",
    "enable_point_cloud_xyzrgb:=false",
    "publish_tf:=true",
    "tf_publish_rate:=10.0",
)
TEST_ONLY_CLEAN_EXEC_ENVIRONMENT: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/opt/ros/noetic/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONPATH": (
        "/opt/ros/noetic/lib/python3/dist-packages:"
        "/usr/lib/python3/dist-packages"),
    "ROS_DISTRO": "noetic",
    "ROS_IP": "127.0.0.1",
    "ROS_MASTER_URI": "http://127.0.0.1:11319",
    "ROS_PYTHON_VERSION": "3",
    "ROS_VERSION": "1",
}

TRUSTED_SYSTEM_PYTHON_ROOTS: Tuple[str, ...] = (
    "/opt/ros/noetic/lib/python3/dist-packages",
    "/usr/lib/python3/dist-packages",
)
PYTHON_ISOLATION_ARGUMENTS: Tuple[str, ...] = ("-I", "-S", "-B", "-c")
ROSLAUNCH_FD_BOOTSTRAP = (
    "import json,runpy,sys\n"
    "if not (sys.flags.isolated and sys.flags.no_site and "
    "sys.flags.dont_write_bytecode): raise SystemExit(91)\n"
    "_roots=json.loads(sys.argv[1])\n"
    "_expected=['/opt/ros/noetic/lib/python3/dist-packages',"
    "'/usr/lib/python3/dist-packages']\n"
    "if _roots != _expected: raise SystemExit(92)\n"
    "if any((not isinstance(_root,str) or not _root.startswith('/') or "
    "'\\\\' in _root or '..' in _root.split('/')) for _root in _roots): "
    "raise SystemExit(93)\n"
    "if any(_root in sys.path for _root in _roots): raise SystemExit(94)\n"
    "sys.path[0:0]=_roots\n"
    "_script=sys.argv[2]\n"
    "if not _script.startswith('/proc/self/fd/'): raise SystemExit(95)\n"
    "sys.argv=[_script,*sys.argv[3:]]\n"
    "runpy.run_path(_script,run_name='__main__')\n"
)
EXECUTION_CLOSURE_MATERIAL_KEYS = {
    "authority_identity",
    "runtime_execution_identity",
    "trusted_install_roots",
    "roslaunch_admission",
    "astra_resolution",
    "clean_exec_environment",
    "clean_exec_environment_report",
    "trusted_system_python_roots",
    "trusted_system_python_root_provenance",
    "runtime_import_probe_stable_material",
}


class AtomicLaunchError(RuntimeError):
    """Stable fail-closed error raised before any exec attempt."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _validate_cli_option_inventory(args: Sequence[str]) -> None:
    """Reject ambiguous CLI material before argparse can normalize it.

    The launcher deliberately has only two caller-controlled fields.  In
    particular, roslaunch path/size/SHA material is not a CLI surface: it is
    obtained from the independently anchored runtime-install admission and is
    recomputed again immediately before exec.
    """
    option_roles = {
        "--mode": "mode",
        "--actual-vendor-launch": "actual_vendor_launch",
    }
    seen: Dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if not isinstance(token, str) or "\x00" in token:
            raise AtomicLaunchError("atomic_cli_argument_invalid")
        role = option_roles.get(token)
        if role is None:
            if token.startswith("-"):
                raise AtomicLaunchError("atomic_cli_unknown_argument")
            raise AtomicLaunchError("atomic_cli_unexpected_positional_argument")
        if role in seen:
            raise AtomicLaunchError("atomic_cli_duplicate_argument:" + role)
        if index + 1 >= len(args) or args[index + 1] in option_roles:
            raise AtomicLaunchError("atomic_cli_missing_argument_value:" + role)
        value = args[index + 1]
        if (not isinstance(value, str) or not value or "\x00" in value
                or value.startswith("--")):
            raise AtomicLaunchError("atomic_cli_missing_argument_value:" + role)
        seen[role] = value
        index += 2
    for option in CLI_REQUIRED_OPTIONS:
        role = option_roles[option]
        if role not in seen:
            raise AtomicLaunchError("atomic_cli_missing_argument:" + role)
    if seen["mode"] != MODE:
        raise AtomicLaunchError("atomic_cli_argument_value_mismatch:mode")


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and value == value.lower()
        and all(item in "0123456789abcdef" for item in value))


def _artifact_identity(record: Any, label: str) -> Dict[str, Any]:
    if not isinstance(record, Mapping):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:" + label)
    path = record.get("path")
    size_bytes = record.get("size_bytes")
    sha256 = record.get("sha256")
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or isinstance(size_bytes, bool) or not isinstance(size_bytes, int)
            or size_bytes <= 0 or not _valid_sha256(sha256)):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:" + label)
    return {"path": path, "size_bytes": size_bytes, "sha256": sha256}


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "execution_closure_material") from error


def _canonical_json_snapshot(value: Any) -> Any:
    try:
        return json.loads(_canonical_json_bytes(value).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "execution_closure_material") from error


def _safe_inventory_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute() and ".." not in path.parts
        and "." not in path.parts and path.as_posix() == value)


def _relative_to_python_root(path: str, root: str) -> Optional[str]:
    try:
        relative = PurePosixPath(path).relative_to(PurePosixPath(root))
    except ValueError:
        return None
    value = relative.as_posix()
    return value if value != "." and _safe_inventory_relative(value) else None


def _validate_python_root_inventory_binding(
        roslaunch: Mapping[str, Any], probe_material: Mapping[str, Any],
        root_records: Sequence[Mapping[str, Any]]) -> None:
    inventories = probe_material.get("python_root_inventories")
    module_specs = probe_material.get("module_specs")
    package_trees = probe_material.get("package_trees")
    auxiliary = probe_material.get("aux_executable_closure")
    if (not isinstance(inventories, Mapping)
            or set(inventories) != {"noetic", "system"}
            or not isinstance(module_specs, Mapping) or not module_specs
            or not isinstance(package_trees, Mapping) or not package_trees
            or not isinstance(auxiliary, Mapping)
            or set(auxiliary) != {"roslaunch"}):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "python_root_inventories")

    validated_inventories: Dict[str, Mapping[str, Any]] = {}
    for record, role, expected_root in zip(
            root_records, ("noetic", "system"),
            TRUSTED_SYSTEM_PYTHON_ROOTS):
        inventory = inventories.get(role)
        if (not isinstance(inventory, Mapping)
                or set(inventory) != {"root_path", "directories", "files"}
                or inventory.get("root_path") != expected_root
                or type(inventory.get("directories")) is not list
                or inventory["directories"] != sorted(inventory["directories"])
                or len(inventory["directories"])
                != len(set(inventory["directories"]))
                or any(not _safe_inventory_relative(item)
                       for item in inventory["directories"])
                or not isinstance(inventory.get("files"), Mapping)
                or not inventory["files"]):
            raise AtomicLaunchError(
                "camera_runtime_install_admission_schema_invalid:"
                "python_root_inventory:" + role)
        directories = set(inventory["directories"])
        files: Dict[str, Mapping[str, Any]] = {}
        for relative, value in inventory["files"].items():
            if not _safe_inventory_relative(relative):
                raise AtomicLaunchError(
                    "camera_runtime_install_admission_schema_invalid:"
                    "python_root_inventory:" + role)
            identity = _artifact_identity(
                value, "python_root_inventory:" + role + ":" + relative)
            expected_path = (
                PurePosixPath(expected_root) / PurePosixPath(relative)
            ).as_posix()
            if identity["path"] != expected_path:
                raise AtomicLaunchError(
                    "camera_runtime_install_python_root_inventory_mismatch:"
                    + role)
            files[relative] = identity
            for parent in PurePosixPath(relative).parents:
                parent_value = parent.as_posix()
                if parent_value != "." and parent_value not in directories:
                    raise AtomicLaunchError(
                        "camera_runtime_install_python_root_inventory_mismatch:"
                        + role)
        for relative in directories:
            parent_value = PurePosixPath(relative).parent.as_posix()
            if parent_value != "." and parent_value not in directories:
                raise AtomicLaunchError(
                    "camera_runtime_install_python_root_inventory_mismatch:"
                    + role)
        manifest_digest = hashlib.sha256(
            _canonical_json_bytes(inventory)).hexdigest()
        if record.get("inventory_manifest_sha256") != manifest_digest:
            raise AtomicLaunchError(
                "camera_runtime_install_python_root_manifest_digest_mismatch:"
                + role)
        if (record.get("directory_count") != len(inventory["directories"])
                or record.get("file_count") != len(inventory["files"])):
            raise AtomicLaunchError(
                "camera_runtime_install_python_root_count_mismatch:" + role)
        validated_inventories[role] = {
            "root_path": expected_root,
            "directories": inventory["directories"],
            "files": files,
        }

    closure_modules = roslaunch.get("module_closure")
    if (not isinstance(closure_modules, Mapping)
            or set(closure_modules) != set(module_specs)):
        raise AtomicLaunchError(
            "camera_runtime_install_python_module_inventory_mismatch")
    for name, spec in module_specs.items():
        if (not isinstance(name, str) or not name
                or not isinstance(spec, Mapping)
                or set(spec) != {
                    "identity", "loader_kind", "expected_version"}
                or spec.get("loader_kind") != "SourceFileLoader"):
            raise AtomicLaunchError(
                "camera_runtime_install_admission_schema_invalid:"
                "runtime_import_module:" + str(name))
        stable_identity = _artifact_identity(
            spec.get("identity"), "runtime_import_module:" + name)
        closure_identity = _artifact_identity(
            closure_modules[name], "roslaunch_module:" + name)
        if stable_identity != closure_identity:
            raise AtomicLaunchError(
                "camera_runtime_install_python_module_inventory_mismatch:" +
                name)
        matches = []
        for role, inventory in validated_inventories.items():
            relative = _relative_to_python_root(
                stable_identity["path"], inventory["root_path"])
            if relative is not None and relative in inventory["files"]:
                matches.append(inventory["files"][relative])
        if matches != [stable_identity]:
            raise AtomicLaunchError(
                "camera_runtime_install_python_module_inventory_mismatch:" +
                name)

    expected_tree_ids: Dict[str, List[str]] = {"noetic": [], "system": []}
    for tree_id, tree in package_trees.items():
        if (not isinstance(tree_id, str) or not tree_id
                or not isinstance(tree, Mapping)
                or set(tree) != {"root_path", "files"}
                or not isinstance(tree.get("root_path"), str)
                or not isinstance(tree.get("files"), Mapping)
                or not tree["files"]):
            raise AtomicLaunchError(
                "camera_runtime_install_admission_schema_invalid:"
                "runtime_import_package_tree:" + str(tree_id))
        matching_roles = [
            role for role, inventory in validated_inventories.items()
            if _relative_to_python_root(
                tree["root_path"], inventory["root_path"]) is not None]
        if len(matching_roles) != 1:
            raise AtomicLaunchError(
                "camera_runtime_install_python_package_tree_mismatch:" +
                tree_id)
        role = matching_roles[0]
        expected_tree_ids[role].append(tree_id)
        inventory = validated_inventories[role]
        for relative, value in tree["files"].items():
            if not _safe_inventory_relative(relative):
                raise AtomicLaunchError(
                    "camera_runtime_install_admission_schema_invalid:"
                    "runtime_import_package_tree:" + tree_id)
            identity = _artifact_identity(
                value, "runtime_import_package_tree:" + tree_id + ":" +
                relative)
            full_path = (
                PurePosixPath(tree["root_path"]) / PurePosixPath(relative)
            ).as_posix()
            inventory_relative = _relative_to_python_root(
                full_path, inventory["root_path"])
            if (identity["path"] != full_path
                    or inventory_relative not in inventory["files"]
                    or inventory["files"][inventory_relative] != identity):
                raise AtomicLaunchError(
                    "camera_runtime_install_python_package_tree_mismatch:" +
                    tree_id)
    for record, role in zip(root_records, ("noetic", "system")):
        if record.get("package_tree_ids") != sorted(expected_tree_ids[role]):
            raise AtomicLaunchError(
                "camera_runtime_install_python_package_tree_set_mismatch:" +
                role)

    roslaunch_identity = _artifact_identity(
        roslaunch.get("executable"), "roslaunch_executable")
    if (_artifact_identity(
            auxiliary.get("roslaunch"), "runtime_import_aux:roslaunch")
            != roslaunch_identity):
        raise AtomicLaunchError(
            "camera_runtime_install_python_aux_inventory_mismatch")


def _runtime_admission_material(
        report: Any, *, test_only: bool) -> Dict[str, Any]:
    if not isinstance(report, Mapping):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:report")
    for key in (
            "authorizes_motion", "authorizes_field_delivery",
            "accepted_by_formal_field_evidence_consumer",
            "formal_acceptance", "delivery_ready"):
        if report.get(key) is not False:
            raise AtomicLaunchError(
                "camera_runtime_install_admission_unsafe_self_report:" + key)
    if test_only:
        valid_state = (
            report.get("test_only") is True
            and report.get("algorithm_validated") is True
            and report.get("validator_unit_test_pass") is True
            and report.get("validated_pass") is False
            and report.get("camera_runtime_install_pass") is False
            and report.get("runtime_import_smoke_validated") is False)
    else:
        valid_state = (
            report.get("test_only") is False
            and report.get("validator_unit_test_pass") is False
            and report.get("validated_pass") is True
            and report.get("camera_runtime_install_pass") is True
            and report.get("runtime_import_smoke_validated") is True)
    if not valid_state or report.get("failures") != []:
        raise AtomicLaunchError("camera_runtime_install_admission_not_bound")
    declared_digest = report.get("execution_closure_digest")
    if not _valid_sha256(declared_digest):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "execution_closure_digest")
    closure_value = report.get("execution_closure_material")
    if (not isinstance(closure_value, Mapping)
            or set(closure_value) != EXECUTION_CLOSURE_MATERIAL_KEYS):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:closure")
    closure = _canonical_json_snapshot(closure_value)
    for key in EXECUTION_CLOSURE_MATERIAL_KEYS:
        if key not in report or _canonical_json_snapshot(report[key]) != closure[key]:
            raise AtomicLaunchError(
                "camera_runtime_install_execution_closure_report_mismatch:" +
                key)
    computed_digest = hashlib.sha256(
        _canonical_json_bytes(closure)).hexdigest()
    if computed_digest != declared_digest:
        raise AtomicLaunchError(
            "camera_runtime_install_execution_closure_digest_mismatch")

    roslaunch = closure["roslaunch_admission"]
    astra = closure["astra_resolution"]
    if (not isinstance(roslaunch, Mapping)
            or not isinstance(astra, Mapping)):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:closure")
    roslaunch_record = roslaunch.get("executable")
    python_record = roslaunch.get("python_executable_target")
    shebang_record = roslaunch.get("shebang_interpreter")
    astra_record = astra.get("launch")
    roslaunch_identity = _artifact_identity(
        roslaunch_record, "roslaunch_executable")
    python_identity = _artifact_identity(
        python_record, "python_executable_target")
    astra_identity = _artifact_identity(
        astra_record, "astra_launch")
    if roslaunch_identity["path"] != ROSLAUNCH_EXECUTABLE:
        raise AtomicLaunchError("camera_runtime_roslaunch_identity_mismatch")
    if (astra_identity["path"]
            != ATTESTED_PRODUCTION_VENDOR_LAUNCH_PATH):
        raise AtomicLaunchError(
            "camera_runtime_astra_launch_preflight_path_mismatch")
    python_name = PurePosixPath(python_identity["path"]).name
    if (not python_name.startswith("python3.")
            or not python_name[len("python3."):].isdigit()
            or not isinstance(shebang_record, Mapping)
            or shebang_record.get("resolved_target_path")
            != python_identity["path"]):
        raise AtomicLaunchError("camera_runtime_python_identity_mismatch")
    runtime_execution = closure["runtime_execution_identity"]
    if (not isinstance(runtime_execution, Mapping)
            or set(runtime_execution) != {
                "uid", "euid", "state_owner_uid", "requires_non_root"}
            or runtime_execution.get("requires_non_root") is not True
            or any(isinstance(runtime_execution.get(key), bool)
                   or not isinstance(runtime_execution.get(key), int)
                   or runtime_execution.get(key) < 0
                   for key in ("uid", "euid", "state_owner_uid"))
            or runtime_execution["uid"] != runtime_execution["euid"]
            or runtime_execution["uid"]
            != runtime_execution["state_owner_uid"]):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "runtime_execution_identity")
    root_paths = closure["trusted_system_python_roots"]
    if (type(root_paths) is not list
            or root_paths != list(TRUSTED_SYSTEM_PYTHON_ROOTS)):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "trusted_system_python_roots")
    root_records_value = closure.get(
        "trusted_system_python_root_provenance")
    if type(root_records_value) is not list or len(root_records_value) != 2:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "trusted_system_python_root_provenance")
    root_records = _canonical_json_snapshot(root_records_value)
    expected_root_owner_uid = (
        int(runtime_execution["uid"]) if test_only else 0)
    roots: List[str] = []
    for record, expected_role, expected_path in zip(
            root_records, ("noetic", "system"),
            TRUSTED_SYSTEM_PYTHON_ROOTS):
        if (not isinstance(record, Mapping)
                or set(record) != {
                    "role", "path", "owner_uid",
                    "inventory_manifest_sha256",
                    "inventory_physical_sha256", "directory_count",
                    "file_count", "package_tree_ids"}
                or record.get("role") != expected_role
                or record.get("path") != expected_path
                or record.get("owner_uid") != expected_root_owner_uid
                or not _valid_sha256(
                    record.get("inventory_manifest_sha256"))
                or not _valid_sha256(
                    record.get("inventory_physical_sha256"))
                or isinstance(record.get("directory_count"), bool)
                or not isinstance(record.get("directory_count"), int)
                or record["directory_count"] < 0
                or isinstance(record.get("file_count"), bool)
                or not isinstance(record.get("file_count"), int)
                or record["file_count"] <= 0
                or type(record.get("package_tree_ids")) is not list
                or not record["package_tree_ids"]
                or record["package_tree_ids"]
                != sorted(record["package_tree_ids"])
                or len(record["package_tree_ids"])
                != len(set(record["package_tree_ids"]))
                or any(not isinstance(item, str) or not item
                       for item in record["package_tree_ids"])):
            raise AtomicLaunchError(
                "camera_runtime_install_admission_schema_invalid:"
                "trusted_system_python_roots")
        roots.append(expected_path)
    probe_material = closure["runtime_import_probe_stable_material"]
    if not isinstance(probe_material, Mapping):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "runtime_import_probe_stable_material")
    _validate_python_root_inventory_binding(
        roslaunch, probe_material, root_records)
    environment = closure["clean_exec_environment"]
    if (not isinstance(environment, Mapping) or not environment
            or any(not isinstance(key, str) or not key
                   or not isinstance(value, str) or "\x00" in value
                   for key, value in environment.items())
            or any(key in environment for key in (
                "PYTHONHOME", "LD_PRELOAD", "ROS_HOSTNAME"))):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "clean_exec_environment")
    if environment.get("PYTHONPATH") != ":".join(roots):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_python_roots_mismatch")
    if (not isinstance(closure["authority_identity"], Mapping)
            or not isinstance(closure["trusted_install_roots"], Mapping)
            or not isinstance(
                closure["clean_exec_environment_report"], Mapping)
            or not isinstance(probe_material, Mapping)):
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:"
            "execution_closure_material")
    # Canonical JSON round-tripping above makes this an immutable value
    # snapshot; a caller cannot mutate a nested report object after the gate.
    try:
        roslaunch_snapshot = json.loads(json.dumps(
            roslaunch_record, allow_nan=False, ensure_ascii=False,
            sort_keys=True))
        python_snapshot = json.loads(json.dumps(
            python_record, allow_nan=False, ensure_ascii=False,
            sort_keys=True))
        shebang_snapshot = json.loads(json.dumps(
            shebang_record, allow_nan=False, ensure_ascii=False,
            sort_keys=True))
        astra_snapshot = json.loads(json.dumps(
            astra_record, allow_nan=False, ensure_ascii=False,
            sort_keys=True))
    except (TypeError, ValueError) as error:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:material") from error
    return {
        "execution_closure_digest": computed_digest,
        "execution_closure_material": closure,
        "runtime_execution_identity": dict(runtime_execution),
        "roslaunch_identity": roslaunch_identity,
        "roslaunch_record": roslaunch_snapshot,
        "python_executable_identity": python_identity,
        "python_executable_record": python_snapshot,
        "shebang_interpreter_record": shebang_snapshot,
        "astra_launch_identity": astra_identity,
        "astra_launch_record": astra_snapshot,
        "trusted_system_python_root_records": root_records,
        "trusted_system_python_roots": list(roots),
        "clean_exec_environment": {
            key: environment[key] for key in sorted(environment)},
    }


def _production_runtime_admission_evaluator() -> Mapping[str, Any]:
    module = _load_exact_runtime_admission_module()
    evaluator = module.__dict__.get(
        "evaluate_camera_runtime_install_admission")
    return evaluator()


def _evaluate_runtime_admission(
        evaluator: Callable[[], Mapping[str, Any]], *, test_only: bool) -> Tuple[
            Mapping[str, Any], Dict[str, Any]]:
    try:
        report = evaluator()
    except AtomicLaunchError:
        raise
    except BaseException as error:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_not_bound") from error
    material = _runtime_admission_material(report, test_only=test_only)
    return report, material


def _validate_runtime_execution_identity(
        identity: Mapping[str, Any], *, test_only: bool) -> None:
    if (int(identity["uid"]) != os.getuid()
            or int(identity["euid"]) != os.geteuid()):
        raise AtomicLaunchError(
            "camera_runtime_execution_identity_mismatch")
    if not test_only and (os.getuid() == 0 or os.geteuid() == 0):
        raise AtomicLaunchError("camera_runtime_root_execution_forbidden")


def _rooted_report_path(environment_root: Path, logical_path: str) -> Path:
    pure = PurePosixPath(logical_path)
    if not pure.is_absolute() or ".." in pure.parts or "\\" in logical_path:
        raise AtomicLaunchError(
            "camera_runtime_install_admission_schema_invalid:path")
    root = Path(environment_root).resolve(strict=True)
    return root.joinpath(*pure.parts[1:])


def _snapshot(value: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _node_identity(value: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "link_count": int(value.st_nlink),
        "owner_uid": int(value.st_uid),
        "owner_gid": int(value.st_gid),
        "size_bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
    }


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: List[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_fd(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise AtomicLaunchError("sealed_memfd_short_write")
        offset += written
    os.lseek(fd, 0, os.SEEK_SET)


def _parent_identity(path: Path) -> List[Dict[str, Any]]:
    identity, failures = PREFLIGHT._absolute_parent_chain_identity(path)
    if failures:
        raise AtomicLaunchError("actual_vendor_launch_parent_chain_invalid")
    return identity


def _trusted_roslaunch_parent_identity(
        path: Path,
        trust_root: Path,
        expected_owner_uid: int) -> List[Dict[str, Any]]:
    """Bind every executable parent to a non-writable trusted root."""
    if (isinstance(expected_owner_uid, bool)
            or not isinstance(expected_owner_uid, int)
            or expected_owner_uid < 0):
        raise AtomicLaunchError("roslaunch_trusted_owner_uid_invalid")
    try:
        root = trust_root.resolve(strict=True)
        path.relative_to(root)
    except (OSError, ValueError) as error:
        raise AtomicLaunchError(
            "roslaunch_executable_outside_trusted_root") from error
    chain: List[Dict[str, Any]] = []
    current = path.parent
    while True:
        try:
            info = current.lstat()
        except OSError as error:
            raise AtomicLaunchError(
                "roslaunch_parent_chain_unavailable") from error
        identity = {"path": str(current), **_node_identity(info)}
        chain.append(identity)
        if PREFLIGHT._is_linklike(info):
            raise AtomicLaunchError("roslaunch_parent_chain_linklike")
        if not stat.S_ISDIR(info.st_mode):
            raise AtomicLaunchError("roslaunch_parent_chain_non_directory")
        if int(info.st_uid) != expected_owner_uid:
            raise AtomicLaunchError("roslaunch_parent_chain_owner_mismatch")
        if int(info.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
            raise AtomicLaunchError("roslaunch_parent_chain_group_other_writable")
        if (expected_owner_uid == os.geteuid()
                and int(info.st_mode) & stat.S_IWUSR):
            raise AtomicLaunchError(
                "roslaunch_parent_chain_writable_by_executor")
        if current == root:
            return chain
        if current.parent == current:
            raise AtomicLaunchError("roslaunch_parent_chain_root_mismatch")
        current = current.parent


def _validate_roslaunch_file_policy(
        info: os.stat_result,
        expected_owner_uid: int) -> None:
    if PREFLIGHT._is_linklike(info) or not stat.S_ISREG(info.st_mode):
        raise AtomicLaunchError("roslaunch_executable_linklike_or_nonregular")
    if int(info.st_nlink) != 1:
        raise AtomicLaunchError("roslaunch_executable_not_unique")
    if int(info.st_uid) != expected_owner_uid:
        raise AtomicLaunchError("roslaunch_executable_owner_mismatch")
    if int(info.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise AtomicLaunchError("roslaunch_executable_group_other_writable")
    if (expected_owner_uid == os.geteuid()
            and int(info.st_mode) & stat.S_IWUSR):
        raise AtomicLaunchError("roslaunch_executable_writable_by_executor")
    if not int(info.st_mode) & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        raise AtomicLaunchError("roslaunch_executable_not_executable")


def _validate_live_path_policy(path: Path) -> None:
    if not path.is_absolute():
        raise AtomicLaunchError("actual_vendor_launch_path_not_absolute")
    if ".." in path.parts or path.name != "dabai_u3.launch":
        raise AtomicLaunchError("actual_vendor_launch_path_policy_mismatch")
    expected = Path(PREFLIGHT.PRODUCTION_VENDOR_LAUNCH_PATH)
    if path.absolute() != expected.absolute():
        raise AtomicLaunchError("actual_vendor_launch_exact_path_mismatch")


def _open_validated_live_fd(
        path: Path, expected_identity: Mapping[str, Any]
        ) -> Tuple[int, bytes, Dict[str, Any]]:
    _validate_live_path_policy(path)
    parent_before = _parent_identity(path)
    try:
        path_before = path.lstat()
    except OSError as error:
        raise AtomicLaunchError("actual_vendor_launch_unavailable") from error
    if (PREFLIGHT._is_linklike(path_before)
            or not stat.S_ISREG(path_before.st_mode)):
        raise AtomicLaunchError("actual_vendor_launch_linklike_or_nonregular")
    if int(path_before.st_nlink) != 1:
        raise AtomicLaunchError("actual_vendor_launch_not_unique")
    try:
        if path.resolve(strict=True) != path:
            raise AtomicLaunchError("actual_vendor_launch_resolved_target_mismatch")
    except OSError as error:
        raise AtomicLaunchError("actual_vendor_launch_unavailable") from error

    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    if nofollow is None or cloexec is None:
        raise AtomicLaunchError("linux_nofollow_cloexec_unavailable")
    try:
        fd = os.open(str(path), os.O_RDONLY | nofollow | cloexec)
    except OSError as error:
        raise AtomicLaunchError("actual_vendor_launch_nofollow_open_failed") from error
    try:
        opened = os.fstat(fd)
        if (_snapshot(opened) != _snapshot(path_before)
                or not stat.S_ISREG(opened.st_mode)
                or int(opened.st_nlink) != 1):
            raise AtomicLaunchError("actual_vendor_launch_open_identity_mismatch")
        if os.get_inheritable(fd):
            raise AtomicLaunchError("actual_vendor_launch_fd_inheritable")
        raw = _read_fd(fd)
        if len(raw) != expected_identity["size_bytes"]:
            raise AtomicLaunchError("actual_vendor_launch_size_bytes_mismatch")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_identity["sha256"]:
            raise AtomicLaunchError("actual_vendor_launch_sha256_mismatch")
        if PREFLIGHT._validate_dabai_launch_bytes(raw):
            raise AtomicLaunchError("actual_vendor_launch_semantic_policy_mismatch")
        path_after = path.lstat()
        parent_after = _parent_identity(path)
        if (_snapshot(path_after) != _snapshot(path_before)
                or _snapshot(os.fstat(fd)) != _snapshot(opened)
                or parent_after != parent_before):
            raise AtomicLaunchError("actual_vendor_launch_changed_during_open")
        return fd, raw, {
            "path": str(path),
            "admission_path": expected_identity["path"],
            "expected_size_bytes": expected_identity["size_bytes"],
            "expected_sha256": expected_identity["sha256"],
            "size_bytes": len(raw),
            "sha256": digest,
            "filesystem_identity": _node_identity(opened),
            "parent_chain_identity": parent_before,
            "fd_inheritable": False,
        }
    except BaseException:
        os.close(fd)
        raise


def _open_validated_roslaunch_executable(
        environment_root: Path,
        expected_identity: Mapping[str, Any],
        *,
        trusted_chain_root: Path,
        expected_owner_uid: int) -> Tuple[int, Path, Dict[str, Any]]:
    expected = _artifact_identity(
        expected_identity, "roslaunch_executable")
    if expected["path"] != ROSLAUNCH_EXECUTABLE:
        raise AtomicLaunchError("camera_runtime_roslaunch_identity_mismatch")
    expected_size_bytes = expected["size_bytes"]
    expected_sha256 = expected["sha256"]
    if (isinstance(expected_size_bytes, bool)
            or not isinstance(expected_size_bytes, int)
            or expected_size_bytes <= 0):
        raise AtomicLaunchError("roslaunch_executable_expected_size_invalid")
    if (not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or expected_sha256 != expected_sha256.lower()
            or any(item not in "0123456789abcdef" for item in expected_sha256)):
        raise AtomicLaunchError("roslaunch_executable_expected_sha256_invalid")
    pure = PurePosixPath(ROSLAUNCH_EXECUTABLE)
    try:
        requested_root = Path(environment_root)
        root_info = requested_root.lstat()
        root = requested_root.resolve(strict=True)
    except OSError as error:
        raise AtomicLaunchError("roslaunch_environment_root_unavailable") from error
    if (PREFLIGHT._is_linklike(root_info)
            or not stat.S_ISDIR(root_info.st_mode)
            or root != requested_root.absolute()):
        raise AtomicLaunchError("roslaunch_environment_root_linklike")
    path = root.joinpath(*pure.parts[1:])
    parent = _trusted_roslaunch_parent_identity(
        path, trusted_chain_root, expected_owner_uid)
    try:
        before = path.lstat()
        _validate_roslaunch_file_policy(before, expected_owner_uid)
        if path.resolve(strict=True) != path:
            raise AtomicLaunchError("roslaunch_executable_resolved_target_mismatch")
    except OSError as error:
        raise AtomicLaunchError("roslaunch_executable_unavailable") from error
    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    if nofollow is None or cloexec is None:
        raise AtomicLaunchError("linux_nofollow_cloexec_unavailable")
    try:
        fd = os.open(str(path), os.O_RDONLY | nofollow | cloexec)
    except OSError as error:
        raise AtomicLaunchError("roslaunch_executable_nofollow_open_failed") from error
    try:
        opened = os.fstat(fd)
        _validate_roslaunch_file_policy(opened, expected_owner_uid)
        if _node_identity(opened) != _node_identity(before):
            raise AtomicLaunchError("roslaunch_executable_open_identity_mismatch")
        if os.get_inheritable(fd):
            raise AtomicLaunchError("roslaunch_executable_fd_inheritable")
        raw = _read_fd(fd)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != expected_size_bytes:
            raise AtomicLaunchError("roslaunch_executable_size_bytes_mismatch")
        if digest != expected_sha256:
            raise AtomicLaunchError("roslaunch_executable_sha256_mismatch")
        after = path.lstat()
        _validate_roslaunch_file_policy(after, expected_owner_uid)
        if (_node_identity(before) != _node_identity(after)
                or _node_identity(opened) != _node_identity(os.fstat(fd))
                or parent != _trusted_roslaunch_parent_identity(
                    path, trusted_chain_root, expected_owner_uid)):
            raise AtomicLaunchError("roslaunch_executable_changed_during_read")
        os.set_inheritable(fd, True)
        if not os.get_inheritable(fd):
            raise AtomicLaunchError("roslaunch_executable_not_inheritable")
        return fd, path, {
            "path": str(path),
            "expected_size_bytes": expected_size_bytes,
            "expected_sha256": expected_sha256,
            "size_bytes": len(raw),
            "sha256": digest,
            "filesystem_identity": _node_identity(after),
            "parent_chain_identity": parent,
            "trusted_chain_root": str(trusted_chain_root),
            "required_owner_uid": expected_owner_uid,
            "group_other_writable": False,
            "fd_inheritable": True,
            "execution_binding": "INHERITABLE_REVALIDATED_SCRIPT_FD",
        }
    except BaseException:
        os.close(fd)
        raise


def _validate_python_executable_file_policy(
        info: os.stat_result, expected_owner_uid: int) -> None:
    if PREFLIGHT._is_linklike(info) or not stat.S_ISREG(info.st_mode):
        raise AtomicLaunchError("python_executable_linklike_or_nonregular")
    if int(info.st_nlink) != 1:
        raise AtomicLaunchError("python_executable_not_unique")
    if int(info.st_uid) != expected_owner_uid:
        raise AtomicLaunchError("python_executable_owner_mismatch")
    if int(info.st_mode) & 0o022:
        raise AtomicLaunchError("python_executable_group_other_writable")
    if (expected_owner_uid == os.geteuid()
            and int(info.st_mode) & stat.S_IWUSR):
        raise AtomicLaunchError("python_executable_writable_by_executor")
    if int(info.st_mode) & 0o555 != 0o555:
        raise AtomicLaunchError("python_executable_not_executable")


def _open_validated_python_executable(
        environment_root: Path,
        expected_identity: Mapping[str, Any],
        *, trusted_chain_root: Path,
        expected_owner_uid: int) -> Tuple[int, Path, Dict[str, Any]]:
    expected = _artifact_identity(
        expected_identity, "python_executable_target")
    pure = PurePosixPath(expected["path"])
    try:
        requested_root = Path(environment_root)
        root_info = requested_root.lstat()
        root = requested_root.resolve(strict=True)
    except OSError as error:
        raise AtomicLaunchError("python_environment_root_unavailable") from error
    if (PREFLIGHT._is_linklike(root_info)
            or not stat.S_ISDIR(root_info.st_mode)
            or root != requested_root.absolute()):
        raise AtomicLaunchError("python_environment_root_linklike")
    path = root.joinpath(*pure.parts[1:])
    parent = _trusted_roslaunch_parent_identity(
        path, trusted_chain_root, expected_owner_uid)
    try:
        before = path.lstat()
        _validate_python_executable_file_policy(before, expected_owner_uid)
        if path.resolve(strict=True) != path:
            raise AtomicLaunchError("python_executable_resolved_target_mismatch")
    except OSError as error:
        raise AtomicLaunchError("python_executable_unavailable") from error
    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    if nofollow is None or cloexec is None:
        raise AtomicLaunchError("linux_nofollow_cloexec_unavailable")
    try:
        fd = os.open(str(path), os.O_RDONLY | nofollow | cloexec)
    except OSError as error:
        raise AtomicLaunchError("python_executable_nofollow_open_failed") from error
    try:
        opened = os.fstat(fd)
        _validate_python_executable_file_policy(opened, expected_owner_uid)
        if _node_identity(opened) != _node_identity(before):
            raise AtomicLaunchError("python_executable_open_identity_mismatch")
        if os.get_inheritable(fd):
            raise AtomicLaunchError("python_executable_fd_inheritable")
        raw = _read_fd(fd)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != expected["size_bytes"]:
            raise AtomicLaunchError("python_executable_size_bytes_mismatch")
        if digest != expected["sha256"]:
            raise AtomicLaunchError("python_executable_sha256_mismatch")
        after = path.lstat()
        _validate_python_executable_file_policy(after, expected_owner_uid)
        if (_node_identity(before) != _node_identity(after)
                or _node_identity(opened) != _node_identity(os.fstat(fd))
                or parent != _trusted_roslaunch_parent_identity(
                    path, trusted_chain_root, expected_owner_uid)):
            raise AtomicLaunchError("python_executable_changed_during_read")
        return fd, path, {
            "path": str(path),
            "admission_path": expected["path"],
            "expected_size_bytes": expected["size_bytes"],
            "expected_sha256": expected["sha256"],
            "size_bytes": len(raw),
            "sha256": digest,
            "filesystem_identity": _node_identity(after),
            "parent_chain_identity": parent,
            "trusted_chain_root": str(trusted_chain_root),
            "required_owner_uid": expected_owner_uid,
            "fd_inheritable": False,
            "execution_binding": "VERSIONED_PYTHON_REVALIDATED_PATH_EXECVE",
        }
    except BaseException:
        os.close(fd)
        raise


def _trusted_fcntl_for_kernel():
    """Return only the independently loaded, freshly re-attested module."""
    if _TRUSTED_FCNTL is None:
        raise AtomicLaunchError("trusted_fcntl_not_attested")
    try:
        provenance = _attest_trusted_fcntl()
    except RuntimeError as error:
        raise AtomicLaunchError("trusted_fcntl_runtime_attestation_failed") from error
    if (provenance != TRUSTED_FCNTL_PROVENANCE
            or provenance.get("validated") is not True):
        raise AtomicLaunchError("trusted_fcntl_provenance_drift")
    return _TRUSTED_FCNTL


def _required_seal_mask(fcntl_module) -> int:
    """Recompute the complete seal mask without trusting a helper report."""
    try:
        namespace = types.ModuleType.__getattribute__(
            fcntl_module, "__dict__")
    except (AttributeError, TypeError) as error:
        raise AtomicLaunchError("linux_seal_constants_unavailable") from error
    values: List[int] = []
    for name in REQUIRED_SEAL_NAMES:
        value = namespace.get(name)
        if (type(value) is not int
                or value <= 0
                or value & (value - 1)):
            raise AtomicLaunchError("linux_seal_constants_invalid")
        values.append(value)
    if len(set(values)) != len(values):
        raise AtomicLaunchError("linux_seal_constants_invalid")
    required = 0
    for value in values:
        required |= value
    return required


def _kernel_seal_identity(fd: int, raw: bytes) -> Dict[str, Any]:
    """Reopen the trust decision at the kernel boundary for one memfd."""
    fcntl_module = _trusted_fcntl_for_kernel()
    namespace = types.ModuleType.__getattribute__(
        fcntl_module, "__dict__")
    get_seals = namespace.get("F_GET_SEALS")
    if type(get_seals) is not int or get_seals <= 0:
        raise AtomicLaunchError("linux_seal_constants_invalid")
    required_seals = _required_seal_mask(fcntl_module)
    try:
        observed_seals = fcntl_module.fcntl(fd, get_seals)
    except (OSError, TypeError, ValueError) as error:
        raise AtomicLaunchError("sealed_memfd_kernel_query_failed") from error
    if type(observed_seals) is not int:
        raise AtomicLaunchError("sealed_memfd_kernel_query_invalid")
    if (observed_seals & required_seals) != required_seals:
        raise AtomicLaunchError("sealed_memfd_required_seals_missing")
    if not os.get_inheritable(fd):
        raise AtomicLaunchError("sealed_memfd_not_inheritable")
    try:
        sealed_stat = os.fstat(fd)
        sealed_raw = _read_fd(fd)
    except OSError as error:
        raise AtomicLaunchError("sealed_memfd_identity_unavailable") from error
    if (not stat.S_ISREG(sealed_stat.st_mode)
            or int(sealed_stat.st_size) != len(raw)
            or sealed_raw != raw):
        raise AtomicLaunchError("sealed_memfd_identity_mismatch")
    proc_path = Path(_sealed_proc_path(fd))
    try:
        proc_stat = proc_path.stat()
        proc_raw = proc_path.read_bytes()
    except OSError as error:
        raise AtomicLaunchError("sealed_memfd_proc_path_unavailable") from error
    if (_snapshot(proc_stat) != _snapshot(sealed_stat)
            or proc_raw != raw):
        raise AtomicLaunchError("sealed_memfd_proc_path_identity_mismatch")
    return {
        "proc_path": str(proc_path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fd_identity": _node_identity(sealed_stat),
        "required_seals": list(REQUIRED_SEAL_NAMES),
        "required_seal_mask": required_seals,
        "observed_seal_mask": observed_seals,
        "inheritable": True,
        "fcntl_provenance": dict(TRUSTED_FCNTL_PROVENANCE),
        "ambient_fcntl_provenance": dict(AMBIENT_FCNTL_PROVENANCE),
    }


def _make_sealed_memfd(raw: bytes) -> Tuple[int, Dict[str, Any]]:
    if not sys.platform.startswith("linux") or not hasattr(os, "memfd_create"):
        raise AtomicLaunchError("linux_sealed_memfd_unavailable")
    fcntl_module = _trusted_fcntl_for_kernel()
    namespace = types.ModuleType.__getattribute__(
        fcntl_module, "__dict__")
    add_seals = namespace.get("F_ADD_SEALS")
    if type(add_seals) is not int or add_seals <= 0:
        raise AtomicLaunchError("linux_seal_constants_invalid")
    required_seals = _required_seal_mask(fcntl_module)
    flags = (
        int(getattr(os, "MFD_CLOEXEC", 0x0001))
        | int(getattr(os, "MFD_ALLOW_SEALING", 0x0002)))
    try:
        fd = os.memfd_create("limo-audited-dabai-launch", flags=flags)
    except OSError as error:
        raise AtomicLaunchError("sealed_memfd_create_failed") from error
    try:
        _write_fd(fd, raw)
        fcntl_module.fcntl(fd, add_seals, required_seals)
        os.set_inheritable(fd, True)
        return fd, _kernel_seal_identity(fd, raw)
    except BaseException:
        os.close(fd)
        raise


def _final_live_identity_check(
        path: Path,
        live_fd: int,
        raw: bytes,
        identity: Mapping[str, Any]) -> None:
    try:
        final_path = path.lstat()
        final_fd = os.fstat(live_fd)
        final_parent = _parent_identity(path)
        final_raw = _read_fd(live_fd)
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise AtomicLaunchError("actual_vendor_launch_final_identity_unavailable") from error
    expected = identity["filesystem_identity"]
    if (resolved != path
            or _node_identity(final_path) != expected
            or _node_identity(final_fd) != expected
            or final_parent != identity["parent_chain_identity"]
            or final_raw != raw
            or len(final_raw) != identity["expected_size_bytes"]
            or hashlib.sha256(final_raw).hexdigest()
            != identity["expected_sha256"]):
        raise AtomicLaunchError("actual_vendor_launch_final_identity_mismatch")
    if os.get_inheritable(live_fd):
        raise AtomicLaunchError("actual_vendor_launch_fd_inheritable")


def _final_roslaunch_identity_check(
        path: Path,
        fd: int,
        identity: Mapping[str, Any]) -> None:
    try:
        before = path.lstat()
        fd_info = os.fstat(fd)
        expected_owner_uid = int(identity["required_owner_uid"])
        trusted_chain_root = Path(str(identity["trusted_chain_root"]))
        _validate_roslaunch_file_policy(before, expected_owner_uid)
        _validate_roslaunch_file_policy(fd_info, expected_owner_uid)
        parent = _trusted_roslaunch_parent_identity(
            path, trusted_chain_root, expected_owner_uid)
        fd_raw = _read_fd(fd)
        path_raw = path.read_bytes()
        after = path.lstat()
        _validate_roslaunch_file_policy(after, expected_owner_uid)
        resolved = path.resolve(strict=True)
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise AtomicLaunchError("roslaunch_executable_final_identity_unavailable") from error
    expected = identity["filesystem_identity"]
    if (resolved != path
            or _node_identity(before) != expected
            or _node_identity(after) != expected
            or _node_identity(fd_info) != expected
            or parent != identity["parent_chain_identity"]
            or len(fd_raw) != identity["expected_size_bytes"]
            or len(path_raw) != identity["expected_size_bytes"]
            or hashlib.sha256(fd_raw).hexdigest() != identity["expected_sha256"]
            or hashlib.sha256(path_raw).hexdigest()
            != identity["expected_sha256"]):
        raise AtomicLaunchError("roslaunch_executable_final_identity_mismatch")
    if not os.get_inheritable(fd):
        raise AtomicLaunchError("roslaunch_executable_not_inheritable")


def _roslaunch_proc_fd_identity(
        fd: int, identity: Mapping[str, Any]) -> Dict[str, Any]:
    proc_path = Path(_sealed_proc_path(fd))
    try:
        descriptor = os.fstat(fd)
        proc_info = proc_path.stat()
        descriptor_raw = _read_fd(fd)
        proc_raw = proc_path.read_bytes()
    except OSError as error:
        raise AtomicLaunchError(
            "roslaunch_executable_proc_fd_unavailable") from error
    if (not os.get_inheritable(fd)
            or _node_identity(descriptor) != identity["filesystem_identity"]
            or _snapshot(proc_info) != _snapshot(descriptor)
            or descriptor_raw != proc_raw
            or len(proc_raw) != identity["expected_size_bytes"]
            or hashlib.sha256(proc_raw).hexdigest()
            != identity["expected_sha256"]):
        raise AtomicLaunchError(
            "roslaunch_executable_proc_fd_identity_mismatch")
    return {
        "proc_path": str(proc_path),
        "size_bytes": len(proc_raw),
        "sha256": hashlib.sha256(proc_raw).hexdigest(),
        "fd_identity": _node_identity(descriptor),
        "inheritable": True,
    }


def _final_python_identity_check(
        path: Path, fd: int, identity: Mapping[str, Any]) -> None:
    try:
        before = path.lstat()
        fd_info = os.fstat(fd)
        expected_owner_uid = int(identity["required_owner_uid"])
        trusted_chain_root = Path(str(identity["trusted_chain_root"]))
        _validate_python_executable_file_policy(before, expected_owner_uid)
        _validate_python_executable_file_policy(fd_info, expected_owner_uid)
        parent = _trusted_roslaunch_parent_identity(
            path, trusted_chain_root, expected_owner_uid)
        fd_raw = _read_fd(fd)
        path_raw = path.read_bytes()
        after = path.lstat()
        _validate_python_executable_file_policy(after, expected_owner_uid)
        resolved = path.resolve(strict=True)
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise AtomicLaunchError(
            "python_executable_final_identity_unavailable") from error
    expected = identity["filesystem_identity"]
    if (resolved != path
            or _node_identity(before) != expected
            or _node_identity(after) != expected
            or _node_identity(fd_info) != expected
            or parent != identity["parent_chain_identity"]
            or len(fd_raw) != identity["expected_size_bytes"]
            or len(path_raw) != identity["expected_size_bytes"]
            or hashlib.sha256(fd_raw).hexdigest()
            != identity["expected_sha256"]
            or hashlib.sha256(path_raw).hexdigest()
            != identity["expected_sha256"]):
        raise AtomicLaunchError("python_executable_final_identity_mismatch")
    if os.get_inheritable(fd):
        raise AtomicLaunchError("python_executable_fd_inheritable")


def _sealed_proc_path(fd: int) -> str:
    return "/proc/self/fd/{}".format(fd)


def _validate_camera_exec_argv(
        actual_vendor_launch: Path,
        python_executable: Path,
        roslaunch_fd: int,
        sealed_fd: int,
        trusted_system_python_roots: Sequence[str],
        argv: Sequence[str]) -> None:
    expected_roslaunch_path = _sealed_proc_path(roslaunch_fd)
    expected_sealed_path = _sealed_proc_path(sealed_fd)
    roots_argument = json.dumps(
        list(trusted_system_python_roots), allow_nan=False,
        ensure_ascii=False, separators=(",", ":"))
    expected = [
        str(python_executable),
        *PYTHON_ISOLATION_ARGUMENTS,
        ROSLAUNCH_FD_BOOTSTRAP,
        roots_argument,
        expected_roslaunch_path,
        expected_sealed_path,
        *CAMERA_ONLY_OVERRIDES,
    ]
    if not argv or argv[0] != str(python_executable):
        raise AtomicLaunchError("camera_only_exec_python_target_mismatch")
    if list(argv[1:5]) != list(PYTHON_ISOLATION_ARGUMENTS):
        raise AtomicLaunchError("camera_only_exec_python_flags_mismatch")
    if len(argv) <= 6 or argv[5] != ROSLAUNCH_FD_BOOTSTRAP:
        raise AtomicLaunchError("camera_only_exec_bootstrap_mismatch")
    if len(argv) <= 7 or argv[6] != roots_argument:
        raise AtomicLaunchError("camera_only_exec_python_roots_mismatch")
    if len(argv) <= 8 or argv[7] != expected_roslaunch_path:
        raise AtomicLaunchError("camera_only_exec_not_using_roslaunch_fd")
    if len(argv) <= 9 or argv[8] != expected_sealed_path:
        raise AtomicLaunchError("camera_only_exec_not_using_sealed_fd")
    if list(argv) != expected:
        raise AtomicLaunchError("camera_only_exec_argv_policy_mismatch")
    if ROSLAUNCH_EXECUTABLE in argv:
        raise AtomicLaunchError("camera_only_exec_argv_uses_roslaunch_path")
    if str(actual_vendor_launch) in argv:
        raise AtomicLaunchError("camera_only_exec_argv_contains_live_path")
    if any(any(token in value.lower() for token in PREFLIGHT.CONTROL_TOKENS)
           for value in argv):
        raise AtomicLaunchError("camera_only_exec_argv_control_token")


def execute_atomic_camera_only(
        actual_vendor_launch: Path,
        *,
        workspace_root: Path = PREFLIGHT.WORKSPACE_ROOT,
        environment_root: Path = Path("/"),
        python_executable: Optional[Path] = None,
        python_version: Optional[Tuple[int, int, int]] = None,
        _exec_function: Callable[
            [str, Sequence[str], Mapping[str, str]], Any] = os.execve,
        _before_exec_hook: Optional[Callable[[], None]] = None,
        _test_trusted_owner_uid: Optional[int] = None,
        _test_runtime_admission_evaluator: Optional[
            Callable[[], Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Repeat preflight, seal exact bytes, then exec fixed camera-only argv.

    Underscored callables are an offline test seam and are unreachable from
    the production CLI.  Production callers cannot supply extra roslaunch
    arguments or choose an executable.
    """
    if not sys.platform.startswith("linux"):
        raise AtomicLaunchError("linux_atomic_launch_required")
    resolved_environment_root = Path(environment_root).resolve(strict=True)
    if _test_runtime_admission_evaluator is not None:
        if (_test_trusted_owner_uid is None
                or _exec_function is os.execve
                or not callable(_test_runtime_admission_evaluator)):
            raise AtomicLaunchError(
                "runtime_admission_test_evaluator_forbidden")
        runtime_admission_evaluator = _test_runtime_admission_evaluator
    else:
        if _before_exec_hook is not None:
            raise AtomicLaunchError("production_before_exec_hook_forbidden")
        if _exec_function is not os.execve:
            raise AtomicLaunchError(
                "production_exec_function_injection_forbidden")
        if _test_trusted_owner_uid is not None:
            raise AtomicLaunchError("production_test_owner_seam_forbidden")
        if python_executable is not None or python_version is not None:
            raise AtomicLaunchError("production_python_override_forbidden")
        if not (sys.flags.isolated and sys.flags.no_site
                and sys.flags.dont_write_bytecode):
            raise AtomicLaunchError("isolated_interpreter_flags_required")
        runtime_admission_evaluator = _production_runtime_admission_evaluator
    if _test_trusted_owner_uid is None:
        if (_exec_function is os.execve
                and resolved_environment_root != Path("/")):
            raise AtomicLaunchError("production_environment_root_mismatch")
        expected_owner_uid = 0
        trusted_chain_root = Path("/")
    else:
        if _exec_function is os.execve:
            raise AtomicLaunchError("test_owner_seam_with_production_exec")
        if (isinstance(_test_trusted_owner_uid, bool)
                or not isinstance(_test_trusted_owner_uid, int)
                or _test_trusted_owner_uid < 0):
            raise AtomicLaunchError("roslaunch_trusted_owner_uid_invalid")
        expected_owner_uid = _test_trusted_owner_uid
        trusted_chain_root = resolved_environment_root
    initial_admission_report, initial_admission_material = (
        _evaluate_runtime_admission(
            runtime_admission_evaluator,
            test_only=_test_runtime_admission_evaluator is not None))
    runtime_execution_identity = initial_admission_material[
        "runtime_execution_identity"]
    _validate_runtime_execution_identity(
        runtime_execution_identity,
        test_only=_test_runtime_admission_evaluator is not None)
    expected_vendor_identity = initial_admission_material[
        "astra_launch_identity"]
    admitted_vendor_path = _rooted_report_path(
        resolved_environment_root, expected_vendor_identity["path"])
    if (Path(actual_vendor_launch).absolute()
            != admitted_vendor_path.absolute()):
        raise AtomicLaunchError("camera_runtime_vendor_launch_identity_mismatch")
    preflight = PREFLIGHT.evaluate_preflight(
        workspace_root=workspace_root,
        environment_root=environment_root,
        actual_vendor_launch=actual_vendor_launch,
        python_executable=python_executable,
        python_version=python_version,
    )
    if preflight.get("preflight_pass") is not True:
        raise AtomicLaunchError("static_preflight_not_passed")

    live_fd = -1
    sealed_fd = -1
    roslaunch_fd = -1
    python_fd = -1
    try:
        roslaunch_fd, roslaunch, roslaunch_identity = (
            _open_validated_roslaunch_executable(
                environment_root,
                initial_admission_material["roslaunch_identity"],
                trusted_chain_root=trusted_chain_root,
                expected_owner_uid=expected_owner_uid))
        python_fd, admitted_python, python_identity = (
            _open_validated_python_executable(
                environment_root,
                initial_admission_material["python_executable_identity"],
                trusted_chain_root=trusted_chain_root,
                expected_owner_uid=expected_owner_uid))
        live_fd, raw, live_identity = _open_validated_live_fd(
            Path(actual_vendor_launch), expected_vendor_identity)
        sealed_fd, sealed_identity = _make_sealed_memfd(raw)
        if _before_exec_hook is not None:
            _before_exec_hook()
        _final_roslaunch_identity_check(
            roslaunch, roslaunch_fd, roslaunch_identity)
        _final_python_identity_check(
            admitted_python, python_fd, python_identity)
        _final_live_identity_check(
            Path(actual_vendor_launch), live_fd, raw, live_identity)
        final_admission_report, final_admission_material = (
            _evaluate_runtime_admission(
                runtime_admission_evaluator,
                test_only=_test_runtime_admission_evaluator is not None))
        if final_admission_report is initial_admission_report:
            raise AtomicLaunchError("camera_runtime_install_admission_replay")
        if final_admission_material != initial_admission_material:
            raise AtomicLaunchError(
                "camera_runtime_install_execution_closure_drift")

        # Recompute the complete identity from the live descriptor and kernel
        # immediately before exec.  A helper report is diagnostic only and
        # must exactly match this host-owned admission result.
        kernel_sealed_identity = _kernel_seal_identity(sealed_fd, raw)
        if dict(sealed_identity) != kernel_sealed_identity:
            raise AtomicLaunchError("sealed_memfd_report_identity_mismatch")
        sealed_identity = kernel_sealed_identity
        sealed_path = str(sealed_identity["proc_path"])
        roslaunch_proc_identity = _roslaunch_proc_fd_identity(
            roslaunch_fd, roslaunch_identity)
        roslaunch_proc_path = str(roslaunch_proc_identity["proc_path"])
        roots = final_admission_material["trusted_system_python_roots"]
        roots_argument = json.dumps(
            roots, allow_nan=False, ensure_ascii=False,
            separators=(",", ":"))
        argv = [
            str(admitted_python),
            *PYTHON_ISOLATION_ARGUMENTS,
            ROSLAUNCH_FD_BOOTSTRAP,
            roots_argument,
            roslaunch_proc_path,
            sealed_path,
            *CAMERA_ONLY_OVERRIDES,
        ]
        _validate_camera_exec_argv(
            Path(actual_vendor_launch), admitted_python, roslaunch_fd,
            sealed_fd, roots, argv)
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": MODE,
            "preflight_pass": True,
            "preflight_delivery_ready": False,
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
            "live_identity": live_identity,
            "sealed_identity": sealed_identity,
            "roslaunch_identity": roslaunch_identity,
            "roslaunch_proc_fd_identity": roslaunch_proc_identity,
            "python_executable_identity": python_identity,
            "exec_target_is_versioned_python": True,
            "python_execution_uses_revalidated_path": True,
            "python_execution_uses_open_fd": False,
            "roslaunch_execution_uses_open_fd": True,
            "roslaunch_execution_uses_revalidated_path": False,
            "roslaunch_fd_inheritable": os.get_inheritable(roslaunch_fd),
            "python_fd_inheritable": os.get_inheritable(python_fd),
            "python_isolation_arguments": list(PYTHON_ISOLATION_ARGUMENTS),
            "python_bootstrap_sha256": hashlib.sha256(
                ROSLAUNCH_FD_BOOTSTRAP.encode("utf-8")).hexdigest(),
            "trusted_system_python_roots": list(roots),
            "runtime_execution_identity": dict(runtime_execution_identity),
            "pythonpath_environment_ignored_by_isolated_mode": True,
            "production_camera_runtime_admission_validated": (
                _test_runtime_admission_evaluator is None),
            "runtime_admission_initial_closure_digest": (
                initial_admission_material["execution_closure_digest"]),
            "runtime_admission_final_closure_digest": (
                final_admission_material["execution_closure_digest"]),
            "runtime_admission_material_recomputed": True,
            "exec_environment_authority": (
                "HOST_RUNTIME_INSTALL_ADMISSION"
                if _test_runtime_admission_evaluator is None
                else "TEST_ONLY_RUNTIME_ADMISSION_EVALUATOR"),
            "exec_environment_ambient_inherited": False,
            "exec_environment": dict(
                final_admission_material["clean_exec_environment"]),
            "argv": argv,
            "uses_live_path_in_argv": str(actual_vendor_launch) in argv,
            "uses_roslaunch_proc_fd_in_argv": argv[7] == roslaunch_proc_path,
            "uses_sealed_proc_fd_in_argv": argv[8] == sealed_path,
        }
        # These are deliberately the final checks before execve.  Roslaunch
        # itself is no longer resolved by pathname in the child: Python opens
        # the already inherited descriptor through /proc/self/fd.
        _final_roslaunch_identity_check(
            roslaunch, roslaunch_fd, roslaunch_identity)
        _final_python_identity_check(
            admitted_python, python_fd, python_identity)
        _final_live_identity_check(
            Path(actual_vendor_launch), live_fd, raw, live_identity)
        if (_roslaunch_proc_fd_identity(roslaunch_fd, roslaunch_identity)
                != roslaunch_proc_identity):
            raise AtomicLaunchError(
                "roslaunch_executable_proc_fd_identity_drift")
        if _kernel_seal_identity(sealed_fd, raw) != sealed_identity:
            raise AtomicLaunchError("sealed_memfd_final_identity_drift")
        _validate_camera_exec_argv(
            Path(actual_vendor_launch), admitted_python, roslaunch_fd,
            sealed_fd, roots, argv)
        try:
            _exec_function(
                str(admitted_python), argv,
                dict(final_admission_material["clean_exec_environment"]))
        except OSError as error:
            raise AtomicLaunchError("camera_only_execve_failed") from error
        if _exec_function is os.execve:
            raise AtomicLaunchError("camera_only_execve_returned")
        report["exec_function_returned"] = True
        return report
    finally:
        if live_fd >= 0:
            os.close(live_fd)
        if sealed_fd >= 0:
            os.close(sealed_fd)
        if roslaunch_fd >= 0:
            os.close(roslaunch_fd)
        if python_fd >= 0:
            os.close(python_fd)


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    values = list(sys.argv[1:] if args is None else args)
    _validate_cli_option_inventory(values)
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Atomically execute only the audited ROS1 DaBai camera launch via "
            "a sealed memfd; no arbitrary roslaunch arguments are accepted."
            ))
    parser.add_argument("--actual-vendor-launch", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=(MODE,))
    return parser.parse_args(values)


def main(args: Optional[Sequence[str]] = None) -> int:
    try:
        options = parse_args(args)
    except AtomicLaunchError as error:
        sys.stderr.write("ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:{}\n".format(
            error.code))
        return 4
    if not (sys.flags.isolated
            and sys.flags.no_site
            and sys.flags.dont_write_bytecode):
        sys.stderr.write(
            "ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
            "isolated_interpreter_flags_required\n")
        return 4
    try:
        execute_atomic_camera_only(
            options.actual_vendor_launch)
    except AtomicLaunchError as error:
        sys.stderr.write("ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:{}\n".format(
            error.code))
        return 4
    # os.execv cannot return on success.  A return is fail-closed even if an
    # unusual replacement implementation was installed by the environment.
    sys.stderr.write("ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:exec_returned\n")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
