"""Pure-software tests for the host-owned camera runtime install gate."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from audit_tools import ros1_camera_runtime_install_admission as ADMISSION


ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_DABAI = (
    ROOT / "evidence" / "perception_v2_field_20260814"
    / "ros1_launch_source" / "dabai_u3.launch")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


class RuntimeInstallFixture:
    """One inert POSIX tree that resembles isolated Noetic install roots."""

    admission_id = "camera-runtime-install-validator-fixture-v1"
    inventory_sentinel = (
        "/opt/ros/noetic/lib/python3/dist-packages/"
        "root_inventory_sentinel.dat")
    inventory_empty_directory = (
        "/opt/ros/noetic/lib/python3/dist-packages/"
        "root_inventory_empty")

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="limo_camera_runtime_install_")
        self.root = Path(self.temporary.name) / "environment"
        self.root.mkdir(mode=0o700)
        self.owner_uid = int(os.getuid())
        self.probe_calls = []
        self.authority_path = self.real(
            "/etc/limo/camera_runtime_install_authority.json")
        self._build_filesystem()
        self.payload = self._authority_payload()
        self.authority_identity = self.write_authority(self.payload)
        self.seal_execution_trees()

    def close(self) -> None:
        self.restore_cleanup_permissions()
        self.temporary.cleanup()

    def __enter__(self) -> "RuntimeInstallFixture":
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()

    def real(self, logical: str) -> Path:
        pure = PurePosixPath(logical)
        if not pure.is_absolute():
            raise AssertionError(logical)
        return self.root.joinpath(*pure.parts[1:])

    def make_directory(self, logical: str, mode: int = 0o755) -> Path:
        path = self.real(logical)
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
        return path

    def write_file(
            self, logical: str, raw: bytes, mode: int = 0o644) -> Path:
        path = self.real(logical)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)
        return path

    def mutate_file(
            self, logical: str, raw: bytes, *, executable: bool = False) -> Path:
        path = self.real(logical)
        path.chmod(0o755 if executable else 0o644)
        path.write_bytes(raw)
        path.chmod(0o555 if executable else 0o444)
        return path

    def install_real_python(self) -> None:
        target = self.real(ADMISSION.PYTHON_TARGET_PATH)
        target.chmod(0o755)
        shutil.copyfile(sys.executable, target)
        target.chmod(0o555)
        payload = copy.deepcopy(self.payload)
        payload["roslaunch"]["python_executable_target"] = self.identity(
            ADMISSION.PYTHON_TARGET_PATH)
        self.write_authority(payload)

    def seal_execution_trees(self) -> None:
        for role in ADMISSION.IMMUTABLE_EXECUTION_ROLES:
            root = self.real(ADMISSION.ROOT_PATHS[role])
            paths = sorted(root.rglob("*"), key=lambda item: len(item.parts),
                           reverse=True)
            for path in paths:
                if path.is_symlink():
                    continue
                metadata = path.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    path.chmod(0o555)
                elif stat.S_ISREG(metadata.st_mode):
                    executable = bool(metadata.st_mode & 0o111)
                    path.chmod(0o555 if executable else 0o444)
            root.chmod(0o555)

    def restore_cleanup_permissions(self) -> None:
        if not self.root.exists():
            return
        for path in [self.root, *self.root.rglob("*")]:
            try:
                if path.is_symlink():
                    continue
                if path.is_dir():
                    path.chmod(0o700)
                elif path.is_file():
                    path.chmod(0o600)
            except OSError:
                pass

    def identity(self, logical: str) -> dict:
        raw = self.real(logical).read_bytes()
        return {
            "path": logical,
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
        }

    def _build_filesystem(self) -> None:
        directory_paths = set(ADMISSION.ROOT_PATHS.values())
        directory_paths.update(ADMISSION.PATH_ENTRIES)
        directory_paths.update(ADMISSION.PYTHONPATH_ENTRIES)
        directory_paths.update(ADMISSION.ROS_PACKAGE_PATH_ENTRIES)
        directory_paths.update(ADMISSION.LD_LIBRARY_PATH_ENTRIES)
        directory_paths.update(ADMISSION.CMAKE_PREFIX_PATH_ENTRIES)
        directory_paths.update((
            ADMISSION.NOETIC_PREFIX + "/etc/ros",
            ADMISSION.NOETIC_PREFIX + "/share/ros",
            ADMISSION.STATE_PREFIX + "/" + self.admission_id,
        ))
        for name in ADMISSION.STATE_SUBDIRECTORIES:
            directory_paths.add(
                ADMISSION.STATE_PREFIX + "/" + self.admission_id + "/" + name)
        for logical in sorted(directory_paths, key=len):
            self.make_directory(logical)
        self.real(ADMISSION.STATE_PREFIX).chmod(0o700)
        state_instance = (
            ADMISSION.STATE_PREFIX + "/" + self.admission_id)
        self.real(state_instance).chmod(0o700)
        for name in ADMISSION.STATE_SUBDIRECTORIES:
            self.real(state_instance + "/" + name).chmod(0o700)

        self.write_file(
            ADMISSION.ROSLAUNCH_PATH,
            b"#!/usr/bin/python3\nfrom roslaunch import main\n",
            0o755)
        self.write_file(
            ADMISSION.PYTHON_TARGET_PATH,
            b"\x7fELF\x02fixture-python-3.8.10\n", 0o755)
        python_entry = self.real(ADMISSION.PYTHON_ENTRY_PATH)
        python_entry.parent.mkdir(parents=True, exist_ok=True)
        python_entry.symlink_to(ADMISSION.PYTHON_ENTRY_LINK_TEXT)

        for name, logical in ADMISSION.MODULE_PATHS.items():
            self.write_file(
                logical,
                ("# pinned fixture module: " + name + "\n").encode("ascii"))
        self.write_file(
            "/opt/ros/noetic/lib/python3/dist-packages/roslaunch/core.py",
            b"# pinned fixture roslaunch core\n")
        self.write_file(
            self.inventory_sentinel,
            b"host-owned complete Python root inventory sentinel\n")
        self.make_directory(self.inventory_empty_directory)

        self.write_file(
            ADMISSION.ASTRA_PACKAGE_XML,
            b"<package><name>astra_camera</name></package>\n")
        self.write_file(
            ADMISSION.ASTRA_LAUNCH_PATH,
            ARCHIVED_DABAI.read_bytes())
        self.write_file(
            ADMISSION.ASTRA_NODE_PATH,
            b"#!/bin/sh\nexit 99\n", 0o755)

    def _clean_environment(self, state_root: str) -> dict:
        return {
            "CMAKE_PREFIX_PATH": ":".join(
                ADMISSION.CMAKE_PREFIX_PATH_ENTRIES),
            "HOME": state_root + "/home",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "LD_LIBRARY_PATH": ":".join(
                ADMISSION.LD_LIBRARY_PATH_ENTRIES),
            "PATH": ":".join(ADMISSION.PATH_ENTRIES),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": ":".join(ADMISSION.PYTHONPATH_ENTRIES),
            "ROS_DISTRO": "noetic",
            "ROS_ETC_DIR": ADMISSION.NOETIC_PREFIX + "/etc/ros",
            "ROS_HOME": state_root + "/ros-home",
            "ROS_IP": "127.0.0.1",
            "ROS_LOG_DIR": state_root + "/log",
            "ROS_MASTER_URI": ADMISSION.ROS_MASTER_URI,
            "ROS_PACKAGE_PATH": ":".join(
                ADMISSION.ROS_PACKAGE_PATH_ENTRIES),
            "ROS_PYTHON_VERSION": "3",
            "ROS_ROOT": ADMISSION.NOETIC_PREFIX + "/share/ros",
            "ROS_VERSION": "1",
            "TMPDIR": state_root + "/tmp",
        }

    def _authority_payload(self) -> dict:
        state_root = ADMISSION.STATE_PREFIX + "/" + self.admission_id
        environment = self._clean_environment(state_root)
        module_closure = {
            name: self.identity(logical)
            for name, logical in ADMISSION.MODULE_PATHS.items()
        }
        package_trees = {}
        for tree_id in sorted(ADMISSION.RUNTIME_IMPORT_REQUIRED_TREE_FILES):
            logical_root = PurePosixPath(
                ADMISSION.MODULE_PATHS[tree_id]).parent.as_posix()
            physical_root = self.real(logical_root)
            package_trees[tree_id] = {
                "root_path": logical_root,
                "files": {
                    path.relative_to(physical_root).as_posix(): self.identity(
                        (PurePosixPath(logical_root)
                         / PurePosixPath(path.relative_to(physical_root).as_posix()))
                        .as_posix())
                    for path in sorted(
                        (item for item in physical_root.rglob("*")
                         if item.is_file()),
                        key=lambda item: item.as_posix())
                },
            }
        python_root_inventories = {}
        for role, logical_root in zip(
                ("noetic", "system"), ADMISSION.PYTHONPATH_ENTRIES):
            physical_root = self.real(logical_root)
            python_root_inventories[role] = {
                "root_path": logical_root,
                "directories": sorted(
                    path.relative_to(physical_root).as_posix()
                    for path in physical_root.rglob("*") if path.is_dir()),
                "files": {
                    path.relative_to(physical_root).as_posix(): self.identity(
                        (PurePosixPath(logical_root) / PurePosixPath(
                            path.relative_to(physical_root).as_posix())).as_posix())
                    for path in sorted(physical_root.rglob("*"))
                    if path.is_file()
                },
            }
        probe_path = Path(ADMISSION.__file__).resolve().with_name(
            ADMISSION.RUNTIME_IMPORT_PROBE_FILENAME)
        probe_raw = probe_path.read_bytes()
        probe_source_identity = {
            "path": str(probe_path),
            "size_bytes": len(probe_raw),
            "sha256": _sha256(probe_raw),
        }
        return {
            "schema_version": 1,
            "marker": ADMISSION.AUTHORITY_MARKER,
            "admission_id": self.admission_id,
            "scope": ADMISSION.SCOPE,
            "test_only": True,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "runtime_family": "ROS1",
            "ros_distro": "noetic",
            "trusted_install_roots": [
                {
                    "role": role,
                    "path": ADMISSION.ROOT_PATHS[role],
                    "owner_uid": self.owner_uid,
                }
                for role in ADMISSION.ROOT_ROLES
            ],
            "roslaunch": {
                "executable": self.identity(ADMISSION.ROSLAUNCH_PATH),
                "shebang_interpreter_entry": ADMISSION.PYTHON_ENTRY_PATH,
                "shebang_interpreter_link_text": (
                    ADMISSION.PYTHON_ENTRY_LINK_TEXT),
                "python_executable_target": self.identity(
                    ADMISSION.PYTHON_TARGET_PATH),
                "python_version": ADMISSION.PYTHON_VERSION,
                "module_closure": module_closure,
            },
            "astra_camera": {
                "package_root": ADMISSION.ASTRA_PACKAGE_ROOT,
                "package_xml": self.identity(ADMISSION.ASTRA_PACKAGE_XML),
                "launch": self.identity(ADMISSION.ASTRA_LAUNCH_PATH),
                "node_executable": self.identity(ADMISSION.ASTRA_NODE_PATH),
            },
            "exec_environment": {
                "policy_id": ADMISSION.EXEC_ENV_POLICY_ID,
                "ros_master_uri": ADMISSION.ROS_MASTER_URI,
                "state_root": state_root,
                "path_entries": list(ADMISSION.PATH_ENTRIES),
                "pythonpath_entries": list(ADMISSION.PYTHONPATH_ENTRIES),
                "ros_package_path_entries": list(
                    ADMISSION.ROS_PACKAGE_PATH_ENTRIES),
                "ld_library_path_entries": list(
                    ADMISSION.LD_LIBRARY_PATH_ENTRIES),
                "cmake_prefix_path_entries": list(
                    ADMISSION.CMAKE_PREFIX_PATH_ENTRIES),
                "expected_environment_sha256": _sha256(
                    _canonical(environment)),
            },
            "runtime_import_probe": {
                "probe_source_identity": probe_source_identity,
                "module_specs": {
                    name: {
                        "identity": dict(identity),
                        "loader_kind": "SourceFileLoader",
                        "expected_version": None,
                    }
                    for name, identity in sorted(module_closure.items())
                },
                "package_trees": package_trees,
                "python_root_inventories": python_root_inventories,
                "customization_inventory": {},
                "aux_executable_closure": {
                    "roslaunch": self.identity(ADMISSION.ROSLAUNCH_PATH)},
            },
        }

    def write_authority(self, payload: dict) -> dict:
        self.authority_path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical(payload)
        self.authority_path.write_bytes(raw)
        self.authority_path.chmod(0o644)
        self.payload = payload
        self.authority_identity = {
            "path": str(self.authority_path.resolve()),
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
        }
        return dict(self.authority_identity)

    def write_authority_raw(self, raw: bytes) -> dict:
        self.authority_path.write_bytes(raw)
        self.authority_path.chmod(0o644)
        self.authority_identity = {
            "path": str(self.authority_path.resolve()),
            "size_bytes": len(raw),
            "sha256": _sha256(raw),
        }
        return dict(self.authority_identity)

    def fake_probe(self, **kwargs: object) -> dict:
        self.probe_calls.append(copy.deepcopy(kwargs))
        module_closure = kwargs["module_closure"]
        package_trees = kwargs["package_trees"]
        python_root_inventories = kwargs["python_root_inventories"]
        customization = kwargs["customization_inventory"]
        auxiliary = kwargs["aux_executable_closure"]
        assets = kwargs["astra_assets"]
        expected_ids = ADMISSION._expected_runtime_import_ids(
            module_closure, package_trees, python_root_inventories,
            customization, auxiliary)
        python_root_directory_provenance = {}
        python_root_file_provenance = {}
        for role, inventory in python_root_inventories.items():
            root = Path(inventory["root_path"])
            root_metadata = root.lstat()
            python_root_directory_provenance[role + ":."] = {
                "path": str(root.resolve(strict=True)),
                **dict(ADMISSION._node_report(root_metadata)),
            }
            for relative in inventory["directories"]:
                path = root / PurePosixPath(relative)
                python_root_directory_provenance[role + ":" + relative] = {
                    "path": str(path.resolve(strict=True)),
                    **dict(ADMISSION._node_report(path.lstat())),
                }
            for relative, identity in inventory["files"].items():
                path = Path(identity["path"])
                metadata = path.lstat()
                python_root_file_provenance[role + ":" + relative] = {
                    **dict(identity),
                    "device": int(metadata.st_dev),
                    "inode": int(metadata.st_ino),
                    "mode": int(metadata.st_mode),
                    "nlink": int(metadata.st_nlink),
                    "mtime_ns": int(metadata.st_mtime_ns),
                }
        request_raw = b"fixture-runtime-import-request"
        request_identity = {
            "path": str((self.root / "fixture-probe-request.json").resolve()),
            "size_bytes": len(request_raw),
            "sha256": _sha256(request_raw),
        }
        child = {
            "schema_version": 1,
            "marker": "LIMO_ROS1_CAMERA_RUNTIME_IMPORT_CHILD_V1",
            "request_id": "a" * 64,
            "request_sha256": request_identity["sha256"],
            "status": "PASS",
            "exit_code": 0,
            "test_only": True,
            "algorithm_validated": True,
            "validator_unit_test_pass": True,
            "validated_pass": False,
            "runtime_import_probe_pass": False,
            "formal_consumer": False,
            "field_evidence_admitted": False,
            "delivery_ready": False,
            "expected_ids": expected_ids,
            "executed_ids": expected_ids,
            "executable_provenance": dict(kwargs["executable_identity"]),
            "probe_source_provenance": dict(kwargs["probe_source_identity"]),
            "module_provenance": {
                name: dict(spec["identity"])
                for name, spec in module_closure.items()
            },
            "module_versions": {
                name: spec["expected_version"]
                for name, spec in module_closure.items()
            },
            "module_loaders": {
                name: spec["loader_kind"]
                for name, spec in module_closure.items()
            },
            "package_tree_file_provenance": {
                tree_id + ":" + relative: dict(identity)
                for tree_id, tree in package_trees.items()
                for relative, identity in tree["files"].items()
            },
            "python_root_directory_provenance": (
                python_root_directory_provenance),
            "python_root_file_provenance": python_root_file_provenance,
            "customization_provenance": {
                name: dict(identity) for name, identity in customization.items()
            },
            "aux_executable_provenance": {
                name: dict(identity) for name, identity in auxiliary.items()
            },
            "astra_asset_provenance": {
                name: dict(identity) for name, identity in assets.items()
            },
            "loaded_nonstdlib_module_ids": sorted(module_closure),
            "child_environment_keys": [
                "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE",
                "PYTHONNOUSERSITE"],
            "forbidden_environment_keys_present": [],
            "isolation": {
                "isolated": True, "no_site": True,
                "dont_write_bytecode": True},
            "sitecustomize_loaded": False,
            "failures": [],
        }
        return {
            "schema_version": 1,
            "gate_id": "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1",
            "admission_mode": "test_only_validator_fixture",
            "read_only": True,
            "starts_ros_graph": False,
            "opens_camera": False,
            "runs_inference": False,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "algorithm_validated": True,
            "validator_unit_test_pass": True,
            "validated_pass": False,
            "runtime_import_probe_pass": False,
            "formal_consumer": False,
            "field_evidence_admitted": False,
            "delivery_ready": False,
            "argv": [
                kwargs["executable_identity"]["path"],
                "-I", "-S", "-B", kwargs["probe_source_identity"]["path"],
                "--child-request", request_identity["path"],
            ],
            "expected_ids": expected_ids,
            "executed_ids": expected_ids,
            "request_identity": request_identity,
            "child_marker": child,
            "parent_environment_restored": True,
            "failures": [],
        }

    def evaluate(self, **kwargs: object) -> dict:
        kwargs.setdefault("_runtime_import_probe_evaluator", self.fake_probe)
        clean_parent = {"PATH": "/ambient/path/is/ignored", "LANG": "C"}
        with mock.patch.dict(os.environ, clean_parent, clear=True):
            return dict(ADMISSION.evaluate_camera_runtime_install_admission(
                self.authority_path,
                self.authority_identity,
                environment_root=self.root,
                _test_owner_uid=self.owner_uid,
                **kwargs))


@unittest.skipUnless(
    os.name == "posix" and hasattr(os, "getuid"),
    "POSIX ownership and symlink semantics required")
class CameraRuntimeInstallAdmissionTest(unittest.TestCase):

    def assert_blocked(self, report: dict, code: str) -> None:
        self.assertFalse(report["algorithm_validated"])
        self.assertFalse(report["validator_unit_test_pass"])
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["camera_runtime_install_pass"])
        self.assertFalse(report["formal_acceptance"])
        self.assertFalse(report["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(report["authorizes_camera_launch"])
        self.assertFalse(report["authorizes_motion"])
        self.assertFalse(report["authorizes_field_delivery"])
        self.assertFalse(report["delivery_ready"])
        self.assertTrue(any(item.startswith(code) for item in report["failures"]),
                        report["failures"])

    def test_host_fixed_production_anchor_is_unbound_and_fail_closed(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            report = dict(
                ADMISSION.evaluate_camera_runtime_install_admission())
        self.assert_blocked(
            report, "camera_runtime_install_authority_anchor_unavailable")
        self.assertFalse(report["production_authority_anchor_bound"])
        self.assertEqual(
            report["authority_selection"]["selection_mode"],
            "host_fixed_production_anchor")

    def test_test_only_fixture_validates_algorithm_but_never_runtime(self) -> None:
        with RuntimeInstallFixture() as fixture:
            report = fixture.evaluate()
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["algorithm_validated"])
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertTrue(report["test_only"])
        self.assertEqual(report["admission_mode"], ADMISSION.TEST_ONLY_MODE)
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["camera_runtime_install_pass"])
        self.assertTrue(report["runtime_import_smoke_required"])
        self.assertFalse(report["runtime_import_smoke_validated"])
        self.assertFalse(report["formal_acceptance"])
        self.assertFalse(report["accepted_by_formal_field_evidence_consumer"])
        self.assertFalse(report["authorizes_camera_launch"])
        self.assertFalse(report["authorizes_motion"])
        self.assertFalse(report["authorizes_field_delivery"])
        self.assertFalse(report["delivery_ready"])
        self.assertEqual(
            report["astra_resolution"]["package_root"],
            "/opt/limo/ros1_camera_runtime/share/astra_camera")
        self.assertEqual(
            report["astra_resolution"]["resolved_node_executable"]["path"],
            "/opt/limo/ros1_camera_runtime/lib/astra_camera/"
            "astra_camera_node")
        self.assertEqual(
            report["roslaunch_admission"]["python_version"], "3.8.10")
        env = report["clean_exec_environment"]
        self.assertEqual(
            env["CMAKE_PREFIX_PATH"],
            "/opt/limo/ros1_camera_runtime:/opt/ros/noetic")
        self.assertNotIn("/src/", env["ROS_PACKAGE_PATH"])
        self.assertNotIn("/devel/", env["LD_LIBRARY_PATH"])
        self.assertTrue(
            report["clean_exec_environment_report"]
            ["environment_derived_from_empty_mapping"])
        self.assertTrue(
            report["clean_exec_environment_report"]["ambient_path_ignored"])

    def test_caller_cannot_supply_a_production_authority_override(self) -> None:
        with RuntimeInstallFixture() as fixture:
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
                report = dict(
                    ADMISSION.evaluate_camera_runtime_install_admission(
                        fixture.authority_path, fixture.authority_identity))
        self.assert_blocked(report, "production_authority_override_forbidden")

    def test_test_seam_requires_test_only_authority_and_nonroot_tree(self) -> None:
        with RuntimeInstallFixture() as fixture:
            payload = copy.deepcopy(fixture.payload)
            payload["test_only"] = False
            fixture.write_authority(payload)
            report = fixture.evaluate()
            self.assert_blocked(report, "test_owner_seam_policy_invalid")
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
                report = dict(
                    ADMISSION.evaluate_camera_runtime_install_admission(
                        fixture.authority_path, fixture.authority_identity,
                        environment_root=Path("/"),
                        _test_owner_uid=fixture.owner_uid))
            self.assert_blocked(report, "test_owner_seam_policy_invalid")

    def test_external_authority_path_size_and_hash_are_exact(self) -> None:
        cases = {
            "path": lambda identity: identity.__setitem__(
                "path", identity["path"] + ".other"),
            "size": lambda identity: identity.__setitem__(
                "size_bytes", identity["size_bytes"] + 1),
            "hash": lambda identity: identity.__setitem__("sha256", "0" * 64),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                identity = dict(fixture.authority_identity)
                mutate(identity)
                fixture.authority_identity = identity
                report = fixture.evaluate()
                self.assert_blocked(report, "authority_external_anchor_mismatch")

    def test_authority_strict_json_rejects_duplicate_nan_and_schema_drift(self) -> None:
        for name in ("duplicate", "nan", "extra", "missing"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                if name == "duplicate":
                    raw = _canonical(fixture.payload).replace(
                        b'"scope":', b'"scope":"duplicate","scope":', 1)
                    fixture.write_authority_raw(raw)
                    expected = "authority_strict_json_invalid"
                elif name == "nan":
                    raw = _canonical(fixture.payload).replace(
                        b'"schema_version":1', b'"schema_version":NaN', 1)
                    fixture.write_authority_raw(raw)
                    expected = "authority_strict_json_invalid"
                else:
                    payload = copy.deepcopy(fixture.payload)
                    if name == "extra":
                        payload["unexpected"] = False
                    else:
                        del payload["scope"]
                    fixture.write_authority(payload)
                    expected = "authority_schema_invalid"
                self.assert_blocked(fixture.evaluate(), expected)

    def test_authority_parent_and_file_policy_rejects_writable_or_linked(self) -> None:
        with RuntimeInstallFixture() as fixture:
            fixture.authority_path.parent.chmod(0o777)
            self.assert_blocked(
                fixture.evaluate(), "authority_parent_chain_invalid")
        with RuntimeInstallFixture() as fixture:
            fixture.authority_path.chmod(0o666)
            self.assert_blocked(
                fixture.evaluate(), "authority_file_policy_invalid")
        with RuntimeInstallFixture() as fixture:
            real = fixture.authority_path.with_suffix(".real.json")
            fixture.authority_path.rename(real)
            fixture.authority_path.symlink_to(real.name)
            fixture.authority_identity = {
                **fixture.authority_identity, "path": str(real.resolve())}
            self.assert_blocked(
                fixture.evaluate(), "authority_file_policy_invalid")

    def test_admission_id_is_a_bounded_single_path_segment(self) -> None:
        for value in ("../escape", "nested/name", "UPPER", "", "a" * 97):
            with self.subTest(value=value), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                payload["admission_id"] = value
                fixture.write_authority(payload)
                self.assert_blocked(
                    fixture.evaluate(), "authority_policy_invalid")

    def test_trusted_root_exact_path_owner_mode_and_link_policy(self) -> None:
        with RuntimeInstallFixture() as fixture:
            payload = copy.deepcopy(fixture.payload)
            payload["trusted_install_roots"][2]["path"] += "/other"
            fixture.write_authority(payload)
            self.assert_blocked(fixture.evaluate(), "trusted_root_schema_invalid")
        with RuntimeInstallFixture() as fixture:
            payload = copy.deepcopy(fixture.payload)
            payload["trusted_install_roots"][2]["owner_uid"] += 1
            fixture.write_authority(payload)
            self.assert_blocked(
                fixture.evaluate(), "trusted_root_test_owner_invalid")
        with RuntimeInstallFixture() as fixture:
            fixture.real(ADMISSION.VENDOR_PREFIX).chmod(0o777)
            self.assert_blocked(
                fixture.evaluate(),
                "trusted_root_immutable_invalid:vendor:writable")

    def test_production_vendor_current_owner_0700_and_0755_are_rejected(self) -> None:
        for mode in (0o700, 0o755):
            with self.subTest(mode=oct(mode)), RuntimeInstallFixture() as fixture:
                vendor = fixture.real(ADMISSION.VENDOR_PREFIX)
                vendor.chmod(mode)
                with self.assertRaises(ADMISSION.AdmissionError) as caught:
                    ADMISSION._validate_immutable_execution_directory_chain(
                        vendor, vendor, 0, "production_vendor_policy")
                self.assertEqual(
                    caught.exception.code,
                    "production_vendor_policy:owner_mismatch")

    def test_root_owned_0755_0644_modes_are_valid_for_non_root_runtime(self) -> None:
        directory = os.stat_result((
            stat.S_IFDIR | 0o755, 1, 1, 2, 0, 0, 0, 0, 0, 0))
        regular = os.stat_result((
            stat.S_IFREG | 0o644, 2, 1, 1, 0, 0, 1, 0, 0, 0))
        group_writable = os.stat_result((
            stat.S_IFREG | 0o664, 3, 1, 1, 0, 0, 1, 0, 0, 0))
        world_writable = os.stat_result((
            stat.S_IFREG | 0o646, 4, 1, 1, 0, 0, 1, 0, 0, 0))
        current_owner = os.stat_result((
            stat.S_IFREG | 0o644, 5, 1, 1, 1000, 0, 1, 0, 0, 0))
        with mock.patch.object(ADMISSION.os, "geteuid", return_value=1000):
            self.assertTrue(
                ADMISSION._immutable_execution_mode_safe(directory, 0))
            self.assertTrue(
                ADMISSION._immutable_execution_mode_safe(regular, 0))
            self.assertFalse(
                ADMISSION._immutable_execution_mode_safe(group_writable, 0))
            self.assertFalse(
                ADMISSION._immutable_execution_mode_safe(world_writable, 0))
            self.assertFalse(
                ADMISSION._immutable_execution_mode_safe(current_owner, 1000))
            reports = ADMISSION._validate_immutable_execution_directory_chain(
                Path("/usr"), Path("/usr/lib"), 0,
                "root_owned_system_chain")
        self.assertTrue(reports)

    def test_execution_root_file_and_parent_owner_write_are_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            fixture.real(ADMISSION.VENDOR_PREFIX).chmod(0o755)
            self.assert_blocked(
                fixture.evaluate(),
                "trusted_root_immutable_invalid:vendor:writable")
        with RuntimeInstallFixture() as fixture:
            fixture.real(ADMISSION.ASTRA_NODE_PATH).chmod(0o755)
            self.assert_blocked(
                fixture.evaluate(),
                "artifact_file_policy_invalid:astra_node_executable")
        with RuntimeInstallFixture() as fixture:
            fixture.real(ADMISSION.ASTRA_NODE_PATH).parent.chmod(0o755)
            self.assert_blocked(
                fixture.evaluate(),
                "artifact_parent_chain_invalid:astra_node_executable:writable")

    def test_roslaunch_path_hash_shebang_and_execute_mode_are_bound(self) -> None:
        cases = ("path", "hash", "shebang", "mode")
        for name in cases:
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                if name == "path":
                    payload = copy.deepcopy(fixture.payload)
                    payload["roslaunch"]["executable"]["path"] += ".other"
                    fixture.write_authority(payload)
                    code = "artifact_exact_path_mismatch:roslaunch_executable"
                elif name == "hash":
                    fixture.mutate_file(
                        ADMISSION.ROSLAUNCH_PATH,
                        b"#!/usr/bin/python3\nraise RuntimeError('drift')\n",
                        executable=True)
                    code = "artifact_identity_mismatch:roslaunch_executable"
                elif name == "shebang":
                    fixture.mutate_file(
                        ADMISSION.ROSLAUNCH_PATH,
                        b"#!/usr/bin/env python3\n", executable=True)
                    payload = copy.deepcopy(fixture.payload)
                    payload["roslaunch"]["executable"] = fixture.identity(
                        ADMISSION.ROSLAUNCH_PATH)
                    fixture.write_authority(payload)
                    code = "roslaunch_shebang_invalid"
                else:
                    fixture.real(ADMISSION.ROSLAUNCH_PATH).chmod(0o700)
                    code = "artifact_file_policy_invalid:roslaunch_executable"
                self.assert_blocked(fixture.evaluate(), code)

    def test_python_entry_target_link_text_hash_and_version_are_bound(self) -> None:
        for name in ("not_link", "link_text", "target_hash", "version"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                entry = fixture.real(ADMISSION.PYTHON_ENTRY_PATH)
                parent = entry.parent
                if name == "not_link":
                    parent.chmod(0o755)
                    entry.unlink()
                    entry.write_bytes(b"python")
                    entry.chmod(0o555)
                    parent.chmod(0o555)
                    code = "python_entry_symlink_required"
                elif name == "link_text":
                    parent.chmod(0o755)
                    entry.unlink()
                    entry.symlink_to("./python3.8")
                    parent.chmod(0o555)
                    code = "python_entry_target_mismatch"
                elif name == "target_hash":
                    fixture.mutate_file(
                        ADMISSION.PYTHON_TARGET_PATH, b"changed target",
                        executable=True)
                    code = "artifact_identity_mismatch:python_executable_target"
                else:
                    payload = copy.deepcopy(fixture.payload)
                    payload["roslaunch"]["python_version"] = "3.8"
                    fixture.write_authority(payload)
                    code = "python_version_declaration_invalid"
                self.assert_blocked(fixture.evaluate(), code)

    def test_module_closure_rejects_missing_extra_empty_and_hash_drift(self) -> None:
        for name in ("missing", "extra", "empty", "hash"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                if name == "missing":
                    del payload["roslaunch"]["module_closure"]["rosgraph"]
                    fixture.write_authority(payload)
                    code = "module_closure_set_invalid"
                elif name == "extra":
                    payload["roslaunch"]["module_closure"]["evil"] = (
                        payload["roslaunch"]["module_closure"]["rosgraph"])
                    fixture.write_authority(payload)
                    code = "module_closure_artifact_invalid:rosgraph"
                elif name == "empty":
                    logical = ADMISSION.MODULE_PATHS["rosgraph"]
                    fixture.mutate_file(logical, b"")
                    payload["roslaunch"]["module_closure"]["rosgraph"] = (
                        fixture.identity(logical))
                    fixture.write_authority(payload)
                    code = "module_closure_artifact_invalid:rosgraph"
                else:
                    fixture.mutate_file(
                        ADMISSION.MODULE_PATHS["rosgraph"],
                        b"raise RuntimeError('drift')\n")
                    code = "artifact_identity_mismatch:module_closure:rosgraph"
                self.assert_blocked(fixture.evaluate(), code)

    def test_regular_unique_files_and_readable_executable_mode_are_required(self) -> None:
        with RuntimeInstallFixture() as fixture:
            node = fixture.real(ADMISSION.ASTRA_NODE_PATH)
            alias = node.with_name("node-hardlink")
            node.parent.chmod(0o755)
            os.link(node, alias)
            node.parent.chmod(0o555)
            self.assert_blocked(
                fixture.evaluate(),
                "artifact_file_policy_invalid:astra_node_executable")
        with RuntimeInstallFixture() as fixture:
            fixture.real(ADMISSION.ASTRA_NODE_PATH).chmod(0o111)
            self.assert_blocked(
                fixture.evaluate(), "artifact_not_executable:astra_node_executable")

    def test_astra_package_launch_node_resolution_and_identity_are_exact(self) -> None:
        for name in ("package", "pkg", "type", "node_path", "node_hash"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                if name == "package":
                    fixture.mutate_file(
                        ADMISSION.ASTRA_PACKAGE_XML,
                        b"<package><name>evil</name></package>")
                    payload["astra_camera"]["package_xml"] = fixture.identity(
                        ADMISSION.ASTRA_PACKAGE_XML)
                    fixture.write_authority(payload)
                    code = "astra_package_identity_invalid"
                elif name in {"pkg", "type"}:
                    attribute = b"pkg=\"evil\"" if name == "pkg" else b"type=\"evil\""
                    fixture.mutate_file(
                        ADMISSION.ASTRA_LAUNCH_PATH,
                        b"<launch><node " + attribute + b" "
                        + (b"type=\"astra_camera_node\"" if name == "pkg"
                           else b"pkg=\"astra_camera\"")
                        + b"/></launch>")
                    payload["astra_camera"]["launch"] = fixture.identity(
                        ADMISSION.ASTRA_LAUNCH_PATH)
                    fixture.write_authority(payload)
                    code = "astra_launch_reference_identity_mismatch"
                elif name == "node_path":
                    payload["astra_camera"]["node_executable"]["path"] += ".x"
                    fixture.write_authority(payload)
                    code = "artifact_exact_path_mismatch:astra_node_executable"
                else:
                    fixture.mutate_file(
                        ADMISSION.ASTRA_NODE_PATH, b"drift", executable=True)
                    code = "artifact_identity_mismatch:astra_node_executable"
                self.assert_blocked(fixture.evaluate(), code)

    def test_astra_rejects_empty_duplicate_name_and_malicious_launch_growth(self) -> None:
        for name, raw, code in (
                ("empty_name", b"<package><name/></package>",
                 "astra_package_identity_invalid"),
                ("duplicate_name",
                 b"<package><name>astra_camera</name><name/></package>",
                 "astra_package_identity_invalid"),
                ("include",
                 b"<launch><include file=\"/tmp/evil.launch\"/></launch>",
                 "astra_launch_reference_identity_mismatch"),
                ("command_param",
                 b"<launch><param name=\"x\" command=\"evil\"/></launch>",
                 "astra_launch_reference_identity_mismatch"),
                ("control_remap",
                 b"<launch><remap from=\"x\" to=\"/cmd_vel\"/></launch>",
                 "astra_launch_reference_identity_mismatch")):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                logical = (ADMISSION.ASTRA_PACKAGE_XML
                           if "name" in name else ADMISSION.ASTRA_LAUNCH_PATH)
                fixture.mutate_file(logical, raw)
                payload = copy.deepcopy(fixture.payload)
                role = "package_xml" if "name" in name else "launch"
                payload["astra_camera"][role] = fixture.identity(logical)
                fixture.write_authority(payload)
                self.assert_blocked(fixture.evaluate(), code)

    def test_exec_environment_exact_policy_uri_paths_digest_and_state_root(self) -> None:
        cases = {
            "uri": ("ros_master_uri", "http://evil:11311/",
                    "exec_environment_master_uri_invalid"),
            "path": ("path_entries", ["/usr/bin"],
                     "exec_environment_policy_invalid"),
            "cmake": ("cmake_prefix_path_entries", ["/opt/ros/noetic"],
                      "exec_environment_policy_invalid"),
            "digest": ("expected_environment_sha256", "0" * 64,
                       "exec_environment_sha256_mismatch"),
            "state": ("state_root", "/tmp/limo",
                      "exec_environment_state_root_invalid"),
        }
        for name, (key, value, code) in cases.items():
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                payload["exec_environment"][key] = value
                fixture.write_authority(payload)
                self.assert_blocked(fixture.evaluate(), code)

    def test_exec_environment_rejects_missing_referenced_directories(self) -> None:
        for logical, code in (
                (ADMISSION.NOETIC_PREFIX + "/etc/ros",
                 "exec_environment_directory_invalid:ros_etc_dir:0"),
                (ADMISSION.NOETIC_PREFIX + "/share/ros",
                 "exec_environment_directory_invalid:ros_root:0")):
            with self.subTest(logical=logical), RuntimeInstallFixture() as fixture:
                target = fixture.real(logical)
                target.parent.chmod(0o755)
                target.rmdir()
                target.parent.chmod(0o555)
                self.assert_blocked(fixture.evaluate(), code)

    def test_state_directories_require_exact_owner_and_user_rwx(self) -> None:
        with RuntimeInstallFixture() as fixture:
            state_home = fixture.real(
                ADMISSION.STATE_PREFIX + "/" + fixture.admission_id + "/home")
            state_home.chmod(0o500)
            self.assert_blocked(
                fixture.evaluate(),
                "exec_environment_state_directory_owner_mode_invalid:home")

    def test_ambient_ros_python_ld_and_cmake_injection_is_fail_closed(self) -> None:
        keys = (
            "ROS_MASTER_URI", "ROS_PACKAGE_PATH", "PYTHONPATH", "PYTHONHOME",
            "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
            "CMAKE_PREFIX_PATH")
        for key in keys:
            with self.subTest(key=key), RuntimeInstallFixture() as fixture:
                with mock.patch.dict(
                        os.environ, {"PATH": "/usr/bin", key: "/injected"},
                        clear=True):
                    report = dict(
                        ADMISSION.evaluate_camera_runtime_install_admission(
                            fixture.authority_path, fixture.authority_identity,
                            environment_root=fixture.root,
                            _test_owner_uid=fixture.owner_uid))
                self.assert_blocked(
                    report, "exec_environment_ambient_forbidden:" + key)

    def test_path_ambient_is_ignored_and_never_copied(self) -> None:
        with RuntimeInstallFixture() as fixture:
            with mock.patch.dict(
                    os.environ, {"PATH": "/evil/bin"}, clear=True):
                report = dict(
                    ADMISSION.evaluate_camera_runtime_install_admission(
                        fixture.authority_path, fixture.authority_identity,
                        environment_root=fixture.root,
                        _test_owner_uid=fixture.owner_uid,
                        _runtime_import_probe_evaluator=fixture.fake_probe))
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertEqual(
            report["clean_exec_environment"]["PATH"],
            ":".join(ADMISSION.PATH_ENTRIES))
        self.assertNotIn("/evil/bin", report["clean_exec_environment"]["PATH"])

    def test_child_replacement_before_final_revalidation_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            target = fixture.real(ADMISSION.ASTRA_NODE_PATH)

            def replace() -> None:
                old = target.with_suffix(".old")
                target.parent.chmod(0o755)
                target.rename(old)
                target.write_bytes(old.read_bytes())
                target.chmod(0o555)
                target.parent.chmod(0o555)

            report = fixture.evaluate(
                _before_final_revalidation_hook=replace)
        self.assert_blocked(report, "install_closure_changed_during_validation")

    def test_in_place_child_drift_before_final_revalidation_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            target = fixture.real(ADMISSION.MODULE_PATHS["roslib"])

            def mutate() -> None:
                fixture.mutate_file(
                    ADMISSION.MODULE_PATHS["roslib"],
                    b"raise RuntimeError('after-first-pass')\n")

            report = fixture.evaluate(
                _before_final_revalidation_hook=mutate)
        self.assert_blocked(
            report, "artifact_identity_mismatch:module_closure:roslib")

    def test_root_mode_drift_before_final_revalidation_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            target = fixture.real(ADMISSION.VENDOR_PREFIX)

            def mutate() -> None:
                target.chmod(0o777)

            report = fixture.evaluate(
                _before_final_revalidation_hook=mutate)
        self.assert_blocked(
            report, "trusted_root_immutable_invalid:vendor:writable")

    def test_authority_drift_before_final_revalidation_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            def mutate() -> None:
                fixture.authority_path.write_bytes(
                    fixture.authority_path.read_bytes() + b" ")

            report = fixture.evaluate(
                _before_final_revalidation_hook=mutate)
        self.assert_blocked(report, "authority_changed_during_validation")

    def test_environment_root_symlink_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            alias = fixture.root.with_name("environment-link")
            alias.symlink_to(fixture.root, target_is_directory=True)
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
                report = dict(
                    ADMISSION.evaluate_camera_runtime_install_admission(
                        fixture.authority_path, fixture.authority_identity,
                        environment_root=alias,
                        _test_owner_uid=fixture.owner_uid))
            self.assert_blocked(
                report, "environment_root_linklike_or_not_directory")

    def test_runtime_import_probe_material_is_exact_and_recomputed_twice(self) -> None:
        with RuntimeInstallFixture() as fixture:
            report = fixture.evaluate()
            self.assertEqual(len(fixture.probe_calls), 2)
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertFalse(report["runs_external_commands"])
        self.assertFalse(report["runs_isolated_python_subprocess"])
        self.assertEqual(
            report["runtime_import_probe_argv"],
            report["runtime_import_probe_report"]["argv"])
        self.assertEqual(
            report["trusted_system_python_roots"],
            list(ADMISSION.PYTHONPATH_ENTRIES))
        material = report["execution_closure_material"]
        self.assertEqual(set(material), {
            "authority_identity", "trusted_install_roots",
            "roslaunch_admission", "astra_resolution",
            "clean_exec_environment", "clean_exec_environment_report",
            "trusted_system_python_roots",
            "trusted_system_python_root_provenance",
            "runtime_import_probe_stable_material",
            "runtime_execution_identity",
        })
        for key in material:
            self.assertEqual(material[key], report[key], key)
        self.assertEqual(
            report["execution_closure_digest"],
            _sha256(_canonical(material)))
        root_provenance = report[
            "trusted_system_python_root_provenance"]
        self.assertEqual(
            [item["role"] for item in root_provenance],
            ["noetic", "system"])
        stable_inventories = report[
            "runtime_import_probe_stable_material"][
                "python_root_inventories"]
        child = report["runtime_import_probe_report"]["child_marker"]
        for item in root_provenance:
            role = item["role"]
            inventory = stable_inventories[role]
            self.assertEqual(
                item["inventory_manifest_sha256"],
                _sha256(_canonical(inventory)))
            self.assertRegex(item["inventory_physical_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(item["directory_count"], len(inventory["directories"]))
            self.assertEqual(item["file_count"], len(inventory["files"]))
            self.assertIn(role + ":.", child["python_root_directory_provenance"])
            for relative in inventory["directories"]:
                self.assertIn(
                    role + ":" + relative,
                    child["python_root_directory_provenance"])
            for relative in inventory["files"]:
                self.assertIn(
                    role + ":" + relative,
                    child["python_root_file_provenance"])
        self.assertIn(
            "root_inventory_empty",
            stable_inventories["noetic"]["directories"])
        self.assertIn(
            "root_inventory_sentinel.dat",
            stable_inventories["noetic"]["files"])

    def test_exact_probe_runs_a_real_isolated_child_in_test_only_mode(self) -> None:
        with RuntimeInstallFixture() as fixture:
            fixture.install_real_python()
            report = fixture.evaluate(
                _runtime_import_probe_evaluator=None)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertTrue(report["runs_external_commands"])
        self.assertTrue(report["runs_isolated_python_subprocess"])
        self.assertEqual(
            report["runtime_import_probe_argv"][1:4], ["-I", "-S", "-B"])
        self.assertFalse(report["runtime_import_probe_pass"])
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["delivery_ready"])

    def test_probe_source_anchor_is_host_fixed_and_ambient_module_is_ignored(self) -> None:
        with RuntimeInstallFixture() as fixture:
            payload = copy.deepcopy(fixture.payload)
            payload["runtime_import_probe"]["probe_source_identity"][
                "sha256"] = "0" * 64
            fixture.write_authority(payload)
            self.assert_blocked(
                fixture.evaluate(),
                "runtime_import_probe_source_anchor_mismatch")
        calls = []
        fake = types.ModuleType(ADMISSION.RUNTIME_IMPORT_PROBE_PRIVATE_MODULE)
        fake.run_camera_runtime_import_probe = (
            lambda **kwargs: calls.append(kwargs))
        with RuntimeInstallFixture() as fixture, mock.patch.dict(
                sys.modules,
                {ADMISSION.RUNTIME_IMPORT_PROBE_PRIVATE_MODULE: fake},
                clear=False):
            report = fixture.evaluate()
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertEqual(calls, [])

    def test_production_rejects_probe_evaluator_and_runner_before_anchor(self) -> None:
        for key, value in (
                ("_runtime_import_probe_evaluator", lambda **kwargs: {}),
                ("_runtime_import_probe_subprocess_runner",
                 lambda *args, **kwargs: None)):
            with self.subTest(key=key), mock.patch.dict(
                    os.environ, {"PATH": "/usr/bin"}, clear=True):
                report = dict(
                    ADMISSION.evaluate_camera_runtime_install_admission(
                        **{key: value}))
            self.assert_blocked(
                report, "production_runtime_import_probe_test_seam_forbidden")

    def test_runtime_import_module_specs_are_exact(self) -> None:
        for name in ("missing", "extra", "loader", "version", "identity"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                specs = payload["runtime_import_probe"]["module_specs"]
                if name == "missing":
                    del specs["rosgraph"]
                    code = "runtime_import_probe_module_set_invalid"
                elif name == "extra":
                    specs["evil"] = copy.deepcopy(specs["rosgraph"])
                    code = "runtime_import_probe_module_set_invalid"
                elif name == "loader":
                    specs["rosgraph"]["loader_kind"] = "ExtensionFileLoader"
                    code = "runtime_import_probe_module_spec_invalid:rosgraph"
                elif name == "version":
                    specs["rosgraph"]["expected_version"] = ""
                    code = "runtime_import_probe_module_spec_invalid:rosgraph"
                else:
                    specs["rosgraph"]["identity"] = copy.deepcopy(
                        specs["roslib"]["identity"])
                    code = "runtime_import_probe_module_spec_invalid:rosgraph"
                fixture.write_authority(payload)
                self.assert_blocked(fixture.evaluate(), code)

    def test_runtime_import_package_tree_exact_set_core_and_hash(self) -> None:
        core_logical = (
            "/opt/ros/noetic/lib/python3/dist-packages/roslaunch/core.py")
        for name in ("undeclared_core", "missing_core", "extra", "hash"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                tree = payload["runtime_import_probe"]["package_trees"][
                    "roslaunch"]
                parent = fixture.real(core_logical).parent
                if name == "undeclared_core":
                    del tree["files"]["core.py"]
                    code = "runtime_import_probe_package_tree_schema_invalid:roslaunch"
                elif name == "missing_core":
                    parent.chmod(0o755)
                    fixture.real(core_logical).unlink()
                    parent.chmod(0o555)
                    code = "runtime_import_probe_python_root_file_set_mismatch:noetic"
                elif name == "extra":
                    parent.chmod(0o755)
                    extra = parent / "undeclared.py"
                    extra.write_bytes(b"raise RuntimeError('never import')\n")
                    extra.chmod(0o444)
                    parent.chmod(0o555)
                    code = "runtime_import_probe_python_root_file_set_mismatch:noetic"
                else:
                    fixture.mutate_file(
                        core_logical, b"raise RuntimeError('drift')\n")
                    code = (
                        "artifact_identity_mismatch:"
                        "runtime_import_python_root:noetic:roslaunch/core.py")
                fixture.write_authority(payload)
                self.assert_blocked(fixture.evaluate(), code)

    def test_runtime_import_customization_surface_must_be_empty(self) -> None:
        for root, filename in (
                (ADMISSION.PYTHONPATH_ENTRIES[0], "sitecustomize.py"),
                (ADMISSION.PYTHONPATH_ENTRIES[1], "usercustomize.py"),
                (ADMISSION.PYTHONPATH_ENTRIES[0], "evil.pth")):
            with self.subTest(filename=filename), RuntimeInstallFixture() as fixture:
                directory = fixture.real(root)
                directory.chmod(0o755)
                marker = directory / filename
                marker.write_bytes(b"raise RuntimeError('must never run')\n")
                marker.chmod(0o444)
                directory.chmod(0o555)
                self.assert_blocked(
                    fixture.evaluate(),
                    "runtime_import_probe_undeclared_customization_artifact")

    def test_runtime_import_python_root_inventory_schema_is_exact(self) -> None:
        for name in (
                "missing_role", "extra_role", "wrong_root",
                "duplicate_directory", "file_identity"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                inventories = payload["runtime_import_probe"][
                    "python_root_inventories"]
                if name == "missing_role":
                    del inventories["system"]
                    code = (
                        "runtime_import_probe_python_root_inventory_"
                        "schema_invalid")
                elif name == "extra_role":
                    inventories["other"] = copy.deepcopy(inventories["system"])
                    code = (
                        "runtime_import_probe_python_root_inventory_"
                        "schema_invalid")
                elif name == "wrong_root":
                    inventories["noetic"]["root_path"] = "/opt/ros/other"
                    code = (
                        "runtime_import_probe_python_root_inventory_"
                        "schema_invalid:noetic")
                elif name == "duplicate_directory":
                    directories = inventories["noetic"]["directories"]
                    directories.append(directories[0])
                    directories.sort()
                    code = (
                        "runtime_import_probe_python_root_inventory_"
                        "schema_invalid:noetic")
                else:
                    inventories["noetic"]["files"][
                        "root_inventory_sentinel.dat"]["sha256"] = "0" * 64
                    code = (
                        "artifact_identity_mismatch:runtime_import_python_root:"
                        "noetic:root_inventory_sentinel.dat")
                fixture.write_authority(payload)
                report = fixture.evaluate()
                self.assertEqual(fixture.probe_calls, [])
                self.assert_blocked(report, code)

    def test_unmanifested_top_level_python_loadables_are_rejected_before_probe(
            self) -> None:
        cases = (
            ("module", "late_unmanifested.py", b"VALUE = 71\n",
             "runtime_import_probe_python_root_file_set_mismatch:noetic"),
            ("package", "late_unmanifested/__init__.py", b"VALUE = 72\n",
             "runtime_import_probe_python_root_directory_set_mismatch:noetic"),
            ("extension", "late_unmanifested.cpython-38-x86_64-linux-gnu.so",
             b"\x7fELF\x02late-unmanifested-extension\n",
             "runtime_import_probe_python_root_file_set_mismatch:noetic"),
        )
        for name, relative, raw, code in cases:
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                root = fixture.real(ADMISSION.PYTHONPATH_ENTRIES[0])
                root.chmod(0o755)
                artifact = root / PurePosixPath(relative)
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(raw)
                artifact.chmod(0o444)
                for parent in artifact.parents:
                    if parent == root:
                        break
                    parent.chmod(0o555)
                root.chmod(0o555)
                report = fixture.evaluate()
                self.assertEqual(fixture.probe_calls, [])
                self.assert_blocked(report, code)

    def test_python_root_linklike_and_hardlink_are_rejected_before_probe(
            self) -> None:
        for name in ("linklike", "hardlink"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                root = fixture.real(ADMISSION.PYTHONPATH_ENTRIES[0])
                root.chmod(0o755)
                if name == "linklike":
                    (root / "late_link.py").symlink_to(
                        "roslaunch/__init__.py")
                else:
                    os.link(
                        fixture.real(fixture.inventory_sentinel),
                        root / "late_hardlink.dat")
                root.chmod(0o555)
                report = fixture.evaluate()
                self.assertEqual(fixture.probe_calls, [])
                self.assert_blocked(
                    report,
                    "runtime_import_python_root_inventory:noetic:"
                    "linklike_or_special")

    def test_python_root_post_admission_mutations_are_rejected(self) -> None:
        for name, expected_code, expected_probe_calls in (
                ("add", "runtime_import_probe_python_root_file_set_mismatch:noetic", 1),
                ("delete", "runtime_import_probe_python_root_file_set_mismatch:noetic", 1),
                ("replace_same_bytes", "install_closure_changed_during_validation", 2),
                ("linklike", "runtime_import_python_root_inventory:noetic:linklike_or_special", 1),
                ("directory_mtime", "install_closure_changed_during_validation", 2),
                ("directory_content", "runtime_import_probe_python_root_directory_set_mismatch:noetic", 1)):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                root = fixture.real(ADMISSION.PYTHONPATH_ENTRIES[0])
                sentinel = fixture.real(fixture.inventory_sentinel)
                empty = fixture.real(fixture.inventory_empty_directory)

                def mutate() -> None:
                    if name == "add":
                        root.chmod(0o755)
                        added = root / "post_admission_add.py"
                        added.write_bytes(b"VALUE = 81\n")
                        added.chmod(0o444)
                        root.chmod(0o555)
                    elif name == "delete":
                        root.chmod(0o755)
                        sentinel.unlink()
                        root.chmod(0o555)
                    elif name == "replace_same_bytes":
                        raw = sentinel.read_bytes()
                        replacement_backup = fixture.root / "sentinel-before-replace"
                        root.chmod(0o755)
                        sentinel.replace(replacement_backup)
                        sentinel.write_bytes(raw)
                        sentinel.chmod(0o444)
                        root.chmod(0o555)
                    elif name == "linklike":
                        root.chmod(0o755)
                        sentinel.unlink()
                        sentinel.symlink_to("roslaunch/__init__.py")
                        root.chmod(0o555)
                    elif name == "directory_mtime":
                        metadata = empty.lstat()
                        os.utime(
                            empty,
                            ns=(int(metadata.st_atime_ns),
                                int(metadata.st_mtime_ns) + 2_000_000_000))
                    else:
                        empty.chmod(0o755)
                        child = empty / "post_admission_empty_directory"
                        child.mkdir(mode=0o555)
                        empty.chmod(0o555)

                report = fixture.evaluate(
                    _before_final_revalidation_hook=mutate)
                self.assertEqual(
                    len(fixture.probe_calls), expected_probe_calls,
                    (name, report["failures"]))
                self.assert_blocked(report, expected_code)

    def test_child_python_root_provenance_is_host_cross_bound(self) -> None:
        for name, field, code in (
                ("file", "python_root_file_provenance",
                 "runtime_import_probe_child_python_root_file_invalid"),
                ("directory", "python_root_directory_provenance",
                 "runtime_import_probe_child_python_root_directory_invalid")):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                def evaluator(**kwargs: object) -> dict:
                    report = fixture.fake_probe(**kwargs)
                    provenance = report["child_marker"][field]
                    key = next(iter(sorted(provenance)))
                    provenance[key]["mtime_ns"] += 1
                    return report

                report = fixture.evaluate(
                    _runtime_import_probe_evaluator=evaluator)
                self.assertEqual(len(fixture.probe_calls), 1)
                self.assert_blocked(report, code)

    def test_runtime_import_aux_closure_is_exact_and_cross_bound(self) -> None:
        for name in ("missing", "extra", "drift"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                payload = copy.deepcopy(fixture.payload)
                auxiliary = payload["runtime_import_probe"][
                    "aux_executable_closure"]
                if name == "missing":
                    del auxiliary["roslaunch"]
                elif name == "extra":
                    auxiliary["other"] = copy.deepcopy(
                        payload["roslaunch"]["executable"])
                else:
                    auxiliary["roslaunch"] = copy.deepcopy(
                        payload["roslaunch"]["python_executable_target"])
                fixture.write_authority(payload)
                self.assert_blocked(
                    fixture.evaluate(), "runtime_import_probe_aux_closure_invalid")

    def test_runtime_import_report_claims_and_provenance_are_recomputed(self) -> None:
        for name in ("missing_key", "ids", "delivery", "module"):
            with self.subTest(name=name), RuntimeInstallFixture() as fixture:
                def evaluator(**kwargs: object) -> dict:
                    report = fixture.fake_probe(**kwargs)
                    if name == "missing_key":
                        del report["parent_environment_restored"]
                    elif name == "ids":
                        report["executed_ids"] = report["executed_ids"][:-1]
                    elif name == "delivery":
                        report["child_marker"]["delivery_ready"] = True
                    else:
                        report["child_marker"]["module_provenance"][
                            "rosgraph"]["sha256"] = "0" * 64
                    return report

                report = fixture.evaluate(
                    _runtime_import_probe_evaluator=evaluator)
                code = {
                    "missing_key": "runtime_import_probe_report_schema_invalid",
                    "ids": (
                        "runtime_import_probe_report_semantic_invalid:"
                        "executed_ids"),
                    "delivery": (
                        "runtime_import_probe_child_semantic_invalid:"
                        "delivery_ready"),
                    "module": (
                        "runtime_import_probe_child_module_invalid:rosgraph"),
                }[name]
                self.assert_blocked(report, code)

    def test_runtime_import_tree_drift_after_first_probe_is_rejected(self) -> None:
        with RuntimeInstallFixture() as fixture:
            directory = fixture.real(
                "/opt/ros/noetic/lib/python3/dist-packages/roslaunch")

            def add_file() -> None:
                directory.chmod(0o755)
                path = directory / "post_probe_drift.py"
                path.write_bytes(b"# drift\n")
                path.chmod(0o444)
                directory.chmod(0o555)

            report = fixture.evaluate(
                _before_final_revalidation_hook=add_file)
            self.assertEqual(len(fixture.probe_calls), 1)
        self.assert_blocked(
            report,
            "runtime_import_probe_python_root_file_set_mismatch:noetic")

    def test_runtime_execution_identity_rejects_root_mismatch_and_state_drift(self) -> None:
        with RuntimeInstallFixture() as fixture:
            authority = copy.deepcopy(fixture.payload)
        with mock.patch.object(ADMISSION.os, "getuid", return_value=1000), \
                mock.patch.object(ADMISSION.os, "geteuid", return_value=1000):
            identity = ADMISSION._runtime_execution_identity(
                authority, production=True)
        self.assertEqual(identity["uid"], 1000)
        for name, uid, euid, code in (
                ("root", 0, 0,
                 "production_runtime_execution_identity_invalid"),
                ("mismatch", 1000, 1001,
                 "production_runtime_execution_identity_invalid"),
                ("state", 2000, 2000, "runtime_state_owner_uid_mismatch")):
            with self.subTest(name=name), \
                    mock.patch.object(ADMISSION.os, "getuid", return_value=uid), \
                    mock.patch.object(ADMISSION.os, "geteuid", return_value=euid), \
                    self.assertRaisesRegex(ADMISSION.AdmissionError, code):
                ADMISSION._runtime_execution_identity(
                    authority, production=True)

    def test_cli_emits_one_strict_marker_and_remains_blocked(self) -> None:
        module = Path(ADMISSION.__file__).resolve()
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "LANG": "C.UTF-8",
        }
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(module)],
            cwd=str(module.parents[1]), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, text=True, timeout=20)
        self.assertEqual(completed.returncode, 4, completed.stderr)
        lines = [line for line in completed.stdout.splitlines() if line]
        self.assertEqual(len(lines), 1, completed.stdout)
        self.assertTrue(lines[0].startswith(ADMISSION.CLI_MARKER))
        payload = json.loads(lines[0][len(ADMISSION.CLI_MARKER):])
        self.assertEqual(
            payload["failures"],
            ["camera_runtime_install_authority_anchor_unavailable"])
        self.assertFalse(payload["validated_pass"])
        self.assertFalse(payload["delivery_ready"])


if __name__ == "__main__":
    unittest.main()
