"""Linux pure-software tests for the sealed DaBai atomic launcher."""

from __future__ import annotations

import copy
import io
import json
import mmap
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

try:
    import fcntl
except ImportError:
    fcntl = None

from audit_tools import ros1_camera_only_atomic_launcher as ATOMIC
from audit_tools import ros1_camera_only_field_preflight as PREFLIGHT
from audit_tools import ros1_camera_runtime_install_admission as INSTALL_ADMISSION
from audit_tools.test_ros1_camera_runtime_install_admission import (
    RuntimeInstallFixture,
)


ROOT = Path(__file__).resolve().parents[1]
PINNED = (
    PREFLIGHT.PREDECESSOR_AUTHORITY_V4,
    PREFLIGHT.FROZEN_CANONICAL_V5,
    PREFLIGHT.FROZEN_REPORT_V4,
    PREFLIGHT.DABAI_LAUNCH,
    PREFLIGHT.FORMAL_CAPTURE_LAUNCH,
)


def _write_executable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o555)


@unittest.skipUnless(
    sys.platform.startswith("linux")
    and hasattr(os, "memfd_create")
    and fcntl is not None,
    "Linux sealed memfd is required for this production-path test")
class Ros1CameraOnlyAtomicLauncherTest(unittest.TestCase):

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="ros1-camera-atomic-launch-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.environment = self.root / "environment"
        self.workspace.mkdir()
        self.environment.mkdir()
        for expected in PINNED:
            source = ROOT.joinpath(*Path(expected["path"]).parts)
            target = self.workspace.joinpath(*Path(expected["path"]).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.archive = ROOT.joinpath(*Path(PREFLIGHT.DABAI_LAUNCH["path"]).parts)
        self.actual_logical = (
            "/opt/limo/ros1_camera_runtime/share/astra_camera/launch/"
            "dabai_u3.launch")
        self.actual = self.environment.joinpath(
            *Path(self.actual_logical).parts[1:])
        self.actual.parent.mkdir(parents=True)
        shutil.copyfile(self.archive, self.actual)

        setup = self.environment / "opt" / "ros" / "noetic" / "setup.bash"
        setup.parent.mkdir(parents=True, exist_ok=True)
        setup.write_bytes(b"# inert fixture; never sourced\n")
        _write_executable(
            self.environment / "usr" / "bin" / "catkin_make",
            b"#!/bin/sh\nexit 99\n")
        _write_executable(
            self.environment / "usr" / "bin" / "cmake",
            b"#!/bin/sh\nexit 99\n")
        self.python = self.environment / "usr" / "bin" / "python3.10"
        _write_executable(self.python, b"#!/bin/sh\nexit 99\n")
        self.roslaunch = (
            self.environment / "opt" / "ros" / "noetic" / "bin" /
            "roslaunch")
        _write_executable(
            self.roslaunch, b"#!/usr/bin/python3\nraise SystemExit(99)\n")
        self.runtime_admission_report = self._make_runtime_admission_report()
        self.admission_calls = 0
        self._freeze_runtime_parent_chains()

    def tearDown(self) -> None:
        for current, directories, unused_files in os.walk(self.environment):
            Path(current).chmod(0o755)
            for name in directories:
                (Path(current) / name).chmod(0o755)
        self.temporary.cleanup()

    def _freeze_runtime_parent_chains(self):
        directories = {self.environment}
        for artifact in (self.roslaunch, self.python):
            current = artifact.parent
            while True:
                directories.add(current)
                if current == self.environment:
                    break
                current = current.parent
        for directory in sorted(
                directories, key=lambda item: len(item.parts), reverse=True):
            directory.chmod(0o555)

    @staticmethod
    def _identity(logical_path: str, path: Path):
        raw = path.read_bytes()
        return {
            "path": logical_path,
            "size_bytes": len(raw),
            "sha256": PREFLIGHT._sha256(raw),
        }

    @staticmethod
    def _declared_identity(logical_path: str):
        raw = ("fixture:" + logical_path).encode("utf-8")
        return {
            "path": logical_path,
            "size_bytes": len(raw),
            "sha256": PREFLIGHT._sha256(raw),
        }

    def _make_runtime_admission_report(self):
        authority = self.environment / "opt" / "limo" / "admission.json"
        authority.parent.mkdir(parents=True, exist_ok=True)
        authority.write_bytes(b"{\"test_only\":true}\n")
        module_paths = {
            "catkin_pkg": (
                "/usr/lib/python3/dist-packages/catkin_pkg/__init__.py"),
            "rosgraph": (
                "/opt/ros/noetic/lib/python3/dist-packages/"
                "rosgraph/__init__.py"),
            "roslaunch": (
                "/opt/ros/noetic/lib/python3/dist-packages/"
                "roslaunch/__init__.py"),
            "roslib": (
                "/opt/ros/noetic/lib/python3/dist-packages/"
                "roslib/__init__.py"),
            "rospkg": "/usr/lib/python3/dist-packages/rospkg/__init__.py",
            "yaml": "/usr/lib/python3/dist-packages/yaml/__init__.py",
        }
        module_closure = {
            name: self._declared_identity(path)
            for name, path in module_paths.items()
        }
        roslaunch_admission = {
            "executable": self._identity(
                ATOMIC.ROSLAUNCH_EXECUTABLE, self.roslaunch),
            "python_executable_target": self._identity(
                "/usr/bin/python3.10", self.python),
            "shebang_interpreter": {
                "entry_path": "/usr/bin/python3",
                "entry_link_text": "python3.10",
                "resolved_target_path": "/usr/bin/python3.10",
                "filesystem_identity": {"test_only": True},
            },
            "python_version": "3.10.12",
            "module_closure": module_closure,
        }
        astra_resolution = {
            "launch": self._identity(self.actual_logical, self.actual),
            "package_xml": {"test_only": True},
            "node_executable": {"test_only": True},
        }
        clean_environment = dict(ATOMIC.TEST_ONLY_CLEAN_EXEC_ENVIRONMENT)
        root_inventories = {}
        package_trees = {}
        for role, root_path, tree_ids in (
                ("noetic", ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS[0],
                 ("rosgraph", "roslaunch", "roslib")),
                ("system", ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS[1],
                 ("catkin_pkg", "rospkg", "yaml"))):
            files = {
                PurePosixPath(path).relative_to(
                    PurePosixPath(root_path)).as_posix(): dict(identity)
                for name, identity in module_closure.items()
                for path in (identity["path"],)
                if name in tree_ids
            }
            if role == "noetic":
                core_path = root_path + "/roslaunch/core.py"
                files["roslaunch/core.py"] = self._declared_identity(core_path)
            directories = sorted({
                parent.as_posix()
                for relative in files
                for parent in PurePosixPath(relative).parents
                if parent.as_posix() != "."
            })
            inventory = {
                "root_path": root_path,
                "directories": directories,
                "files": {key: files[key] for key in sorted(files)},
            }
            root_inventories[role] = inventory
            for tree_id in tree_ids:
                tree_root = root_path + "/" + tree_id
                tree_files = {
                    relative.rsplit("/", 1)[-1]: dict(identity)
                    for relative, identity in files.items()
                    if relative.startswith(tree_id + "/")
                }
                package_trees[tree_id] = {
                    "root_path": tree_root,
                    "files": tree_files,
                }
        root_provenance = []
        for role in ("noetic", "system"):
            inventory = root_inventories[role]
            root_provenance.append({
                "role": role,
                "path": inventory["root_path"],
                "owner_uid": os.getuid(),
                "inventory_manifest_sha256": PREFLIGHT._sha256(
                    ATOMIC._canonical_json_bytes(inventory)),
                "inventory_physical_sha256": PREFLIGHT._sha256(
                    ("physical:" + role).encode("ascii")),
                "directory_count": len(inventory["directories"]),
                "file_count": len(inventory["files"]),
                "package_tree_ids": sorted(
                    tree_id for tree_id, tree in package_trees.items()
                    if tree["root_path"].startswith(
                        inventory["root_path"] + "/")),
            })
        runtime_probe_material = {
            "probe_source_identity": self._declared_identity(
                "/host/audit_tools/ros1_camera_runtime_import_probe.py"),
            "module_specs": {
                name: {
                    "identity": dict(identity),
                    "loader_kind": "SourceFileLoader",
                    "expected_version": None,
                }
                for name, identity in sorted(module_closure.items())
            },
            "package_trees": {
                key: package_trees[key] for key in sorted(package_trees)},
            "python_root_inventories": root_inventories,
            "customization_inventory": {},
            "aux_executable_closure": {
                "roslaunch": dict(roslaunch_admission["executable"])},
            "probe_gate_id": "ROS1_NOETIC_CAMERA_RUNTIME_IMPORT_PROBE_V1",
            "probe_admission_mode": "test_only_validator_fixture",
            "expected_ids": ["test-only-runtime-import"],
            "executed_ids": ["test-only-runtime-import"],
            "parent_environment_restored": True,
            "isolation": {
                "isolated": True, "no_site": True,
                "dont_write_bytecode": True},
            "formal_consumer": False,
            "field_evidence_admitted": False,
            "delivery_ready": False,
        }
        closure = {
            "authority_identity": self._identity(
                "/opt/limo/admission.json", authority),
            "runtime_execution_identity": {
                "uid": os.getuid(),
                "euid": os.geteuid(),
                "state_owner_uid": os.getuid(),
                "requires_non_root": True,
            },
            "trusted_install_roots": {
                "noetic": {"path": "/opt/ros/noetic", "test_only": True},
                "system": {"path": "/usr", "test_only": True},
                "vendor": {
                    "path": "/opt/limo/ros1_camera_runtime",
                    "test_only": True,
                },
            },
            "roslaunch_admission": roslaunch_admission,
            "astra_resolution": astra_resolution,
            "clean_exec_environment": clean_environment,
            "clean_exec_environment_report": {
                "policy_id": "test-only-clean-environment",
                "state_reports": {"test_only": True},
            },
            "trusted_system_python_roots": list(
                ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS),
            "trusted_system_python_root_provenance": root_provenance,
            "runtime_import_probe_stable_material": runtime_probe_material,
        }
        digest = PREFLIGHT._sha256(ATOMIC._canonical_json_bytes(closure))
        return {
            "test_only": True,
            "algorithm_validated": True,
            "validator_unit_test_pass": True,
            "validated_pass": False,
            "camera_runtime_install_pass": False,
            "runtime_import_smoke_validated": False,
            "authorizes_motion": False,
            "authorizes_field_delivery": False,
            "accepted_by_formal_field_evidence_consumer": False,
            "formal_acceptance": False,
            "delivery_ready": False,
            "failures": [],
            "execution_closure_digest": digest,
            "execution_closure_material": copy.deepcopy(closure),
            **copy.deepcopy(closure),
        }

    def _runtime_admission(self):
        self.admission_calls += 1
        return copy.deepcopy(self.runtime_admission_report)

    @staticmethod
    def _refresh_report(report):
        closure = report["execution_closure_material"]
        for key in ATOMIC.EXECUTION_CLOSURE_MATERIAL_KEYS:
            report[key] = copy.deepcopy(closure[key])
        report["execution_closure_digest"] = PREFLIGHT._sha256(
            ATOMIC._canonical_json_bytes(closure))
        return report

    def _execute(self, fake_exec, hook=None, evaluator=None):
        with mock.patch.object(
                ATOMIC.PREFLIGHT, "PRODUCTION_VENDOR_LAUNCH_PATH",
                str(self.actual)):
            return ATOMIC.execute_atomic_camera_only(
                self.actual,
                workspace_root=self.workspace,
                environment_root=self.environment,
                python_executable=self.python,
                python_version=(3, 10, 12),
                _exec_function=fake_exec,
                _before_exec_hook=hook,
                _test_trusted_owner_uid=os.getuid(),
                _test_runtime_admission_evaluator=(
                    evaluator or self._runtime_admission),
            )

    def _prepare_exact_runtime_fixture(
            self, fixture: RuntimeInstallFixture) -> Path:
        fixture.restore_cleanup_permissions()
        fixture.write_file(
            INSTALL_ADMISSION.NOETIC_PREFIX + "/setup.bash",
            b"# inert test-only setup; never sourced\n")
        fixture.write_file(
            "/usr/bin/catkin_make", b"#!/bin/sh\nexit 99\n", 0o755)
        fixture.write_file(
            "/usr/bin/cmake", b"#!/bin/sh\nexit 99\n", 0o755)
        fixture.install_real_python()
        fixture.real(INSTALL_ADMISSION.ROSLAUNCH_PATH).chmod(0o755)
        fixture.real(INSTALL_ADMISSION.ASTRA_NODE_PATH).chmod(0o755)
        fixture.seal_execution_trees()
        for artifact in (
                fixture.real(INSTALL_ADMISSION.ROSLAUNCH_PATH),
                fixture.real(INSTALL_ADMISSION.PYTHON_TARGET_PATH)):
            current = artifact.parent
            while current != fixture.root:
                current.chmod(0o555)
                current = current.parent
        fixture.root.chmod(0o555)
        return fixture.real(INSTALL_ADMISSION.ASTRA_LAUNCH_PATH)

    def _execute_exact_runtime_fixture(
            self, fixture: RuntimeInstallFixture, fake_exec_calls: list,
            *, hook=None, admission_reports=None):
        actual = fixture.real(INSTALL_ADMISSION.ASTRA_LAUNCH_PATH)
        reports = [] if admission_reports is None else admission_reports

        def exact_admission():
            report = fixture.evaluate(_runtime_import_probe_evaluator=None)
            reports.append(report)
            return report

        with mock.patch.object(
                ATOMIC.PREFLIGHT, "PRODUCTION_VENDOR_LAUNCH_PATH",
                str(actual)), mock.patch.object(
                    tempfile, "tempdir", "/tmp"):
            return ATOMIC.execute_atomic_camera_only(
                actual,
                workspace_root=self.workspace,
                environment_root=fixture.root,
                python_executable=fixture.real(
                    INSTALL_ADMISSION.PYTHON_TARGET_PATH),
                python_version=(3, 8, 10),
                _exec_function=lambda *args: fake_exec_calls.append(args),
                _before_exec_hook=hook,
                _test_trusted_owner_uid=os.getuid(),
                _test_runtime_admission_evaluator=exact_admission,
            )

    def test_fake_exec_consumes_only_inheritable_fully_sealed_memfd(self):
        observed = {}

        def fake_exec(executable_path, argv, environment):
            roslaunch_fd = int(Path(argv[7]).name)
            sealed_fd = int(Path(argv[8]).name)
            write_blocked = False
            try:
                os.write(sealed_fd, b"x")
            except OSError:
                write_blocked = True
            grow_blocked = False
            try:
                os.ftruncate(
                    sealed_fd, len(self.archive.read_bytes()) + 1)
            except OSError:
                grow_blocked = True
            shrink_blocked = False
            try:
                os.ftruncate(sealed_fd, 1)
            except OSError:
                shrink_blocked = True
            mmap_write_blocked = False
            try:
                writable = mmap.mmap(
                    sealed_fd, len(self.archive.read_bytes()),
                    access=mmap.ACCESS_WRITE)
            except OSError:
                mmap_write_blocked = True
            else:
                writable.close()
            observed.update({
                "executable_path": executable_path,
                "executable_raw": Path(executable_path).read_bytes(),
                "argv": list(argv),
                "environment": dict(environment),
                "roslaunch_raw": Path(argv[7]).read_bytes(),
                "raw": Path(argv[8]).read_bytes(),
                "inheritable": os.get_inheritable(sealed_fd),
                "roslaunch_inheritable": os.get_inheritable(roslaunch_fd),
                "seals": fcntl.fcntl(sealed_fd, fcntl.F_GET_SEALS),
                "write_blocked": write_blocked,
                "grow_blocked": grow_blocked,
                "shrink_blocked": shrink_blocked,
                "mmap_write_blocked": mmap_write_blocked,
            })

        report = self._execute(fake_exec)
        required_mask = (
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
            fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        self.assertTrue(report["exec_function_returned"])
        self.assertFalse(report["uses_live_path_in_argv"])
        self.assertTrue(report["uses_sealed_proc_fd_in_argv"])
        self.assertEqual(observed["executable_path"], str(self.python))
        self.assertEqual(observed["executable_raw"], self.python.read_bytes())
        self.assertEqual(
            observed["environment"],
            dict(ATOMIC.TEST_ONLY_CLEAN_EXEC_ENVIRONMENT))
        self.assertFalse(report["exec_environment_ambient_inherited"])
        self.assertFalse(report["production_camera_runtime_admission_validated"])
        self.assertEqual(observed["raw"], self.archive.read_bytes())
        self.assertEqual(observed["roslaunch_raw"], self.roslaunch.read_bytes())
        self.assertTrue(observed["inheritable"])
        self.assertTrue(observed["roslaunch_inheritable"])
        self.assertTrue(observed["write_blocked"])
        self.assertTrue(observed["grow_blocked"])
        self.assertTrue(observed["shrink_blocked"])
        self.assertTrue(observed["mmap_write_blocked"])
        self.assertEqual(observed["seals"] & required_mask, required_mask)
        self.assertEqual(
            observed["argv"][1:5], list(ATOMIC.PYTHON_ISOLATION_ARGUMENTS))
        self.assertEqual(observed["argv"][5], ATOMIC.ROSLAUNCH_FD_BOOTSTRAP)
        self.assertEqual(
            json.loads(observed["argv"][6]),
            list(ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS))
        self.assertTrue(observed["argv"][7].startswith("/proc/self/fd/"))
        self.assertTrue(observed["argv"][8].startswith("/proc/self/fd/"))
        self.assertNotIn(str(self.actual), observed["argv"])
        self.assertIsNot(ATOMIC.PREFLIGHT, PREFLIGHT)
        for key in (
                "authorizes_field_delivery",
                "accepted_by_formal_field_evidence_consumer",
                "formal_consumer", "formal_acceptance", "formal_tf_pass",
                "formal_3d_pass", "formal_latency_pass", "delivery_ready"):
            self.assertFalse(report[key], key)
        self.assertEqual(report["formal_four_scene_frame_denominator"], 0)
        self.assertTrue(report["roslaunch_execution_uses_open_fd"])
        self.assertFalse(report["roslaunch_execution_uses_revalidated_path"])
        self.assertTrue(report["exec_target_is_versioned_python"])
        self.assertFalse(report["python_fd_inheritable"])

    def test_exec_time_live_rewrite_cannot_change_sealed_launch_bytes(self):
        baseline = self.archive.read_bytes()
        observed = {}

        def fake_exec(executable_fd, argv, environment):
            # This occurs after the launcher's final live path/FD check.  The
            # pathname can still be changed, but roslaunch's argument is the
            # already sealed immutable object and therefore retains baseline.
            self.actual.write_bytes(b"<launch><node pkg='evil'/></launch>\n")
            observed["argv"] = list(argv)
            observed["sealed_raw"] = Path(argv[8]).read_bytes()
            observed["sealed_sha256"] = PREFLIGHT._sha256(
                observed["sealed_raw"])

        report = self._execute(fake_exec)
        self.assertTrue(report["exec_function_returned"])
        self.assertEqual(observed["sealed_raw"], baseline)
        self.assertEqual(
            observed["sealed_sha256"], PREFLIGHT.DABAI_LAUNCH["sha256"])
        self.assertNotIn(str(self.actual), observed["argv"])
        self.assertTrue(observed["argv"][8].startswith("/proc/self/fd/"))

    def test_fake_exec_target_is_exact_revalidated_versioned_python_path(self):
        observed = {}

        def fake_exec(executable_path, argv, environment):
            observed["target"] = executable_path
            observed["argv"] = list(argv)

        report = self._execute(fake_exec)
        self.assertEqual(observed["target"], str(self.python))
        self.assertEqual(observed["argv"][0], str(self.python))
        self.assertTrue(report["roslaunch_execution_uses_open_fd"])
        self.assertFalse(report["roslaunch_execution_uses_revalidated_path"])

    def test_roslaunch_swap_before_final_check_is_rejected(self):
        called = []

        def swap():
            self.roslaunch.parent.chmod(0o755)
            old = self.roslaunch.with_name("roslaunch.original")
            self.roslaunch.rename(old)
            _write_executable(self.roslaunch, old.read_bytes())
            self.roslaunch.parent.chmod(0o555)

        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_executable_final_identity_mismatch"):
            self._execute(lambda *_: called.append(True), swap)
        self.assertEqual(called, [])

    def test_roslaunch_same_inode_rewrite_before_final_check_is_rejected(self):
        called = []

        def rewrite():
            raw = bytearray(self.roslaunch.read_bytes())
            raw[-2] ^= 1
            self.roslaunch.chmod(0o755)
            with self.roslaunch.open("r+b", buffering=0) as stream:
                stream.seek(0)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.roslaunch.chmod(0o555)

        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_executable_final_identity_mismatch"):
            self._execute(lambda *_: called.append(True), rewrite)
        self.assertEqual(called, [])

    def test_roslaunch_group_writable_file_is_rejected(self):
        called = []
        self.roslaunch.chmod(0o775)
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_executable_group_other_writable"):
            self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_roslaunch_group_writable_parent_is_rejected(self):
        called = []
        self.roslaunch.parent.chmod(0o775)
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_parent_chain_group_other_writable"):
            self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_current_owner_writable_file_and_parent_are_rejected(self):
        for role, path, code in (
                ("file", self.roslaunch,
                 "roslaunch_executable_writable_by_executor"),
                ("parent", self.roslaunch.parent,
                 "roslaunch_parent_chain_writable_by_executor")):
            with self.subTest(role=role):
                path.chmod(0o755)
                called = []
                try:
                    with self.assertRaisesRegex(ATOMIC.AtomicLaunchError, code):
                        self._execute(lambda *_: called.append(True))
                finally:
                    path.chmod(0o555)
                self.assertEqual(called, [])

    def test_root_owned_0755_executables_are_allowed_for_non_root_runtime(self):
        root_owned_0755 = os.stat_result((
            stat.S_IFREG | 0o755, 1, 1, 1, 0, 0, 1, 0, 0, 0))
        with mock.patch.object(ATOMIC.os, "geteuid", return_value=1000):
            ATOMIC._validate_roslaunch_file_policy(root_owned_0755, 0)
            ATOMIC._validate_python_executable_file_policy(root_owned_0755, 0)

    def test_production_root_execution_identity_is_rejected(self):
        identity = {
            "uid": 0, "euid": 0, "state_owner_uid": 0,
            "requires_non_root": True,
        }
        with mock.patch.object(ATOMIC.os, "getuid", return_value=0), \
                mock.patch.object(ATOMIC.os, "geteuid", return_value=0), \
                self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "camera_runtime_root_execution_forbidden"):
            ATOMIC._validate_runtime_execution_identity(
                identity, test_only=False)

    def test_roslaunch_owner_policy_is_root_in_production_mode(self):
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_executable_owner_mismatch"):
            ATOMIC._validate_roslaunch_file_policy(
                self.roslaunch.lstat(), 0)

    def test_test_admission_seam_cannot_be_combined_with_production_exec(self):
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "runtime_admission_test_evaluator_forbidden"):
            ATOMIC.execute_atomic_camera_only(
                self.actual,
                workspace_root=self.workspace,
                environment_root=self.environment,
                python_executable=self.python,
                python_version=(3, 10, 12),
                _exec_function=os.execve,
                _test_trusted_owner_uid=os.getuid(),
                _test_runtime_admission_evaluator=self._runtime_admission,
            )

    def test_production_direct_call_rejects_test_seams_before_admission(self):
        cases = {
            "fake_exec": ({"_exec_function": lambda *_: None},
                          "production_exec_function_injection_forbidden"),
            "before_exec_hook": ({"_before_exec_hook": lambda: None},
                                 "production_before_exec_hook_forbidden"),
            "python_override": ({"python_executable": self.python},
                                "production_python_override_forbidden"),
        }
        for name, (kwargs, code) in cases.items():
            with self.subTest(name=name), mock.patch.object(
                    ATOMIC, "_production_runtime_admission_evaluator"
                    ) as evaluator, self.assertRaisesRegex(
                        ATOMIC.AtomicLaunchError, code):
                ATOMIC.execute_atomic_camera_only(self.actual, **kwargs)
            evaluator.assert_not_called()

    def test_production_direct_call_requires_isolated_interpreter_flags(self):
        bad_flags = types.SimpleNamespace(
            isolated=0, no_site=1, dont_write_bytecode=1)
        with mock.patch.object(ATOMIC.sys, "flags", bad_flags), \
                mock.patch.object(
                ATOMIC, "_production_runtime_admission_evaluator"
                ) as evaluator, self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "isolated_interpreter_flags_required"):
            ATOMIC.execute_atomic_camera_only(self.actual)
        evaluator.assert_not_called()

    def test_ambient_ros_and_python_environment_is_never_inherited(self):
        observed = {}
        injected = {
            "PYTHONPATH": "/tmp/fake-python",
            "PYTHONHOME": "/tmp/fake-home",
            "ROS_PACKAGE_PATH": "/tmp/evil-first",
            "ROS_MASTER_URI": "http://shared-master:11311",
            "LD_PRELOAD": "/tmp/fake.so",
        }

        def fake_exec(executable, argv, environment):
            observed.update(environment)

        with mock.patch.dict(os.environ, injected, clear=False):
            report = self._execute(fake_exec)
        self.assertEqual(
            observed, dict(ATOMIC.TEST_ONLY_CLEAN_EXEC_ENVIRONMENT))
        for key, value in injected.items():
            self.assertNotEqual(observed.get(key), value, key)
        self.assertEqual(report["exec_environment"], observed)
        self.assertEqual(report["exec_environment_authority"],
                         "TEST_ONLY_RUNTIME_ADMISSION_EVALUATOR")

    def test_production_cli_is_blocked_until_runtime_admission_is_bound(self):
        launcher = ROOT / "audit_tools" / "ros1_camera_only_atomic_launcher.py"
        completed = subprocess.run([
            sys.executable, "-I", "-S", "-B", str(launcher),
            "--mode", ATOMIC.MODE,
            "--actual-vendor-launch", str(self.actual),
        ], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
           text=True, timeout=30)
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(
            completed.stderr,
            "ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:"
            "camera_runtime_install_admission_not_bound\n")

    def test_wrong_admitted_roslaunch_anchor_is_rejected(self):
        called = []
        report = copy.deepcopy(self.runtime_admission_report)
        report["execution_closure_material"]["roslaunch_admission"][
            "executable"]["sha256"] = "0" * 64
        report["execution_closure_material"][
            "runtime_import_probe_stable_material"][
                "aux_executable_closure"]["roslaunch"]["sha256"] = "0" * 64
        self._refresh_report(report)
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "roslaunch_executable_sha256_mismatch"):
            self._execute(
                lambda *_: called.append(True),
                evaluator=lambda: copy.deepcopy(report))
        self.assertEqual(called, [])

    def test_admission_failure_and_forged_digest_stop_before_preflight(self):
        cases = []
        failed = copy.deepcopy(self.runtime_admission_report)
        failed["algorithm_validated"] = False
        failed["validator_unit_test_pass"] = False
        failed["failures"] = ["test_only_failure"]
        cases.append(("admission_failed", failed,
                      "camera_runtime_install_admission_not_bound"))
        forged = copy.deepcopy(self.runtime_admission_report)
        forged["execution_closure_digest"] = "0" * 64
        cases.append((
            "forged_digest", forged,
            "camera_runtime_install_execution_closure_digest_mismatch"))
        unsafe = copy.deepcopy(self.runtime_admission_report)
        unsafe["delivery_ready"] = True
        cases.append((
            "unsafe_self_report", unsafe,
            "camera_runtime_install_admission_unsafe_self_report:"
            "delivery_ready"))
        for name, report, code in cases:
            with self.subTest(name=name), mock.patch.object(
                    ATOMIC.PREFLIGHT, "evaluate_preflight") as preflight:
                called = []
                with self.assertRaisesRegex(
                        ATOMIC.AtomicLaunchError, code):
                    self._execute(
                        lambda *_: called.append(True),
                        evaluator=lambda report=report: copy.deepcopy(report))
                preflight.assert_not_called()
                self.assertEqual(called, [])

    def test_same_admission_report_object_replay_is_rejected(self):
        shared = self.runtime_admission_report
        called = []
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "camera_runtime_install_admission_replay"):
            self._execute(
                lambda *_: called.append(True), evaluator=lambda: shared)
        self.assertEqual(called, [])

    def test_test_only_report_cannot_be_consumed_as_production(self):
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "camera_runtime_install_admission_not_bound"):
            ATOMIC._runtime_admission_material(
                copy.deepcopy(self.runtime_admission_report),
                test_only=False)

    def test_admitted_astra_path_must_equal_attested_preflight_path(self):
        report = copy.deepcopy(self.runtime_admission_report)
        report["execution_closure_material"]["astra_resolution"]["launch"][
            "path"] = (
                "/opt/limo/ros1_camera_runtime/share/astra_camera/launch/"
                "other.launch")
        self._refresh_report(report)
        called = []
        with mock.patch.object(
                ATOMIC.PREFLIGHT, "evaluate_preflight") as preflight, \
                self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "camera_runtime_astra_launch_preflight_path_mismatch"):
            self._execute(
                lambda *_: called.append(True),
                evaluator=lambda: copy.deepcopy(report))
        preflight.assert_not_called()
        self.assertEqual(called, [])

    def test_real_test_only_install_admission_report_cross_binds_material(self):
        with mock.patch.object(tempfile, "tempdir", "/var/tmp"):
            runtime_fixture = RuntimeInstallFixture()
        with runtime_fixture as fixture:
            fixture.install_real_python()
            report = fixture.evaluate(_runtime_import_probe_evaluator=None)
            material = ATOMIC._runtime_admission_material(
                report, test_only=True)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertEqual(
            material["astra_launch_identity"]["path"],
            ATOMIC.ATTESTED_PRODUCTION_VENDOR_LAUNCH_PATH)
        self.assertEqual(
            material["trusted_system_python_roots"],
            list(ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS))
        self.assertEqual(
            material["trusted_system_python_root_records"],
            report["trusted_system_python_root_provenance"])

    def test_real_test_only_install_admission_drives_full_fake_exec_path(self):
        observed = {}

        def fake_exec(executable, argv, environment):
            observed["executable"] = executable
            observed["argv"] = list(argv)
            observed["environment"] = dict(environment)

        with mock.patch.object(tempfile, "tempdir", "/var/tmp"):
            runtime_fixture = RuntimeInstallFixture()
        with runtime_fixture as fixture:
            # The install fixture intentionally models only admission assets.
            # Add the three inert static-preflight toolchain markers before
            # resealing its execution trees; none is executed by this test.
            fixture.restore_cleanup_permissions()
            fixture.write_file(
                INSTALL_ADMISSION.NOETIC_PREFIX + "/setup.bash",
                b"# inert test-only setup; never sourced\n")
            fixture.write_file(
                "/usr/bin/catkin_make", b"#!/bin/sh\nexit 99\n", 0o755)
            fixture.write_file(
                "/usr/bin/cmake", b"#!/bin/sh\nexit 99\n", 0o755)
            fixture.install_real_python()
            fixture.real(INSTALL_ADMISSION.ROSLAUNCH_PATH).chmod(0o755)
            fixture.real(INSTALL_ADMISSION.ASTRA_NODE_PATH).chmod(0o755)
            fixture.seal_execution_trees()
            for artifact in (
                    fixture.real(INSTALL_ADMISSION.ROSLAUNCH_PATH),
                    fixture.real(INSTALL_ADMISSION.PYTHON_TARGET_PATH)):
                current = artifact.parent
                while current != fixture.root:
                    current.chmod(0o555)
                    current = current.parent
            fixture.root.chmod(0o555)
            actual = fixture.real(INSTALL_ADMISSION.ASTRA_LAUNCH_PATH)
            # Keep the probe's transient request directory outside the
            # launch's /var/tmp parent chain.  Otherwise creating a sibling
            # below the same temp root legitimately changes its mtime and exercises the
            # production parent-drift rejection for a test-only layout that
            # does not resemble the real /opt launch path.
            probe_temp_root = Path("/tmp")
            self.assertTrue(probe_temp_root.is_dir())

            def exact_admission():
                return fixture.evaluate(_runtime_import_probe_evaluator=None)

            with mock.patch.object(tempfile, "tempdir", str(probe_temp_root)):
                precheck = exact_admission()
            self.assertEqual(precheck["failures"], [])
            with mock.patch.object(
                    ATOMIC.PREFLIGHT, "PRODUCTION_VENDOR_LAUNCH_PATH",
                    str(actual)), mock.patch.object(
                        tempfile, "tempdir", str(probe_temp_root)):
                report = ATOMIC.execute_atomic_camera_only(
                    actual,
                    workspace_root=self.workspace,
                    environment_root=fixture.root,
                    python_executable=fixture.real(
                        INSTALL_ADMISSION.PYTHON_TARGET_PATH),
                    python_version=(3, 8, 10),
                    _exec_function=fake_exec,
                    _test_trusted_owner_uid=os.getuid(),
                    _test_runtime_admission_evaluator=exact_admission,
                )
        self.assertTrue(report["exec_function_returned"])
        self.assertFalse(report["production_camera_runtime_admission_validated"])
        self.assertFalse(report["formal_acceptance"])
        self.assertFalse(report["delivery_ready"])
        self.assertEqual(
            observed["executable"],
            str(fixture.real(INSTALL_ADMISSION.PYTHON_TARGET_PATH)))
        self.assertEqual(
            observed["environment"], report["exec_environment"])
        self.assertTrue(report["uses_roslaunch_proc_fd_in_argv"])
        self.assertTrue(report["uses_sealed_proc_fd_in_argv"])

    def test_root_inventory_material_is_exactly_cross_bound(self):
        cases = {}

        def wrong_manifest(material):
            material["trusted_system_python_root_provenance"][0][
                "inventory_manifest_sha256"] = "0" * 64

        def wrong_physical_schema(material):
            material["trusted_system_python_root_provenance"][0][
                "inventory_physical_sha256"] = "not-a-sha256"

        def wrong_count(material):
            material["trusted_system_python_root_provenance"][0][
                "file_count"] += 1

        def wrong_module_inventory(material):
            inventory = material["runtime_import_probe_stable_material"][
                "python_root_inventories"]["noetic"]
            inventory["files"]["roslaunch/__init__.py"]["sha256"] = "1" * 64
            material["trusted_system_python_root_provenance"][0][
                "inventory_manifest_sha256"] = PREFLIGHT._sha256(
                    ATOMIC._canonical_json_bytes(inventory))

        def wrong_tree_set(material):
            material["trusted_system_python_root_provenance"][0][
                "package_tree_ids"] = ["roslaunch", "roslib"]

        cases["manifest"] = (
            wrong_manifest,
            "camera_runtime_install_python_root_manifest_digest_mismatch:noetic")
        cases["physical"] = (
            wrong_physical_schema,
            "camera_runtime_install_admission_schema_invalid:"
            "trusted_system_python_roots")
        cases["count"] = (
            wrong_count,
            "camera_runtime_install_python_root_count_mismatch:noetic")
        cases["module"] = (
            wrong_module_inventory,
            "camera_runtime_install_python_module_inventory_mismatch:roslaunch")
        cases["tree_set"] = (
            wrong_tree_set,
            "camera_runtime_install_python_package_tree_set_mismatch:noetic")
        for name, (mutate, code) in cases.items():
            report = copy.deepcopy(self.runtime_admission_report)
            mutate(report["execution_closure_material"])
            self._refresh_report(report)
            called = []
            with self.subTest(name=name), self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError, code):
                self._execute(
                    lambda *_: called.append(True),
                    evaluator=lambda report=report: copy.deepcopy(report))
            self.assertEqual(called, [])

    def _assert_preexisting_exact_python_root_artifact_blocked(
            self, logical_path: str, raw: bytes,
            expected_failure: str = (
                "runtime_import_probe_python_root_file_set_mismatch:noetic")
            ) -> None:
        with mock.patch.object(tempfile, "tempdir", "/var/tmp"):
            runtime_fixture = RuntimeInstallFixture()
        with runtime_fixture as fixture:
            fixture.restore_cleanup_permissions()
            fixture.write_file(logical_path, raw)
            self._prepare_exact_runtime_fixture(fixture)
            fake_exec_calls = []
            reports = []
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "camera_runtime_install_admission_not_bound"):
                self._execute_exact_runtime_fixture(
                    fixture, fake_exec_calls, admission_reports=reports)
        self.assertEqual(fake_exec_calls, [])
        self.assertEqual(len(reports), 1)
        self.assertTrue(any(
            expected_failure in failure
            for failure in reports[0]["failures"]),
            reports[0]["failures"])

    def test_exact_fixture_preexisting_extra_top_level_py_blocks_exec(self):
        self._assert_preexisting_exact_python_root_artifact_blocked(
            INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0] + "/late_extra.py",
            b"VALUE = 73\n")

    def test_exact_fixture_preexisting_extra_package_blocks_exec(self):
        self._assert_preexisting_exact_python_root_artifact_blocked(
            INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0] +
            "/late_unmanifested/__init__.py",
            b"VALUE = 73\n",
            "runtime_import_probe_python_root_directory_set_mismatch:noetic")

    def test_exact_fixture_preexisting_extra_extension_blocks_exec(self):
        self._assert_preexisting_exact_python_root_artifact_blocked(
            INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0] +
            "/late_unmanifested.cpython-38-x86_64-linux-gnu.so",
            b"\x7fELF\x02late-unmanifested-extension\n")

    def _assert_post_initial_exact_root_drift_blocked(
            self, mutate, expected_code: str) -> None:
        with mock.patch.object(tempfile, "tempdir", "/var/tmp"):
            runtime_fixture = RuntimeInstallFixture()
        with runtime_fixture as fixture:
            self._prepare_exact_runtime_fixture(fixture)
            fake_exec_calls = []
            reports = []
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError, expected_code):
                self._execute_exact_runtime_fixture(
                    fixture, fake_exec_calls,
                    hook=lambda: mutate(fixture),
                    admission_reports=reports)
        self.assertEqual(fake_exec_calls, [])
        self.assertGreaterEqual(len(reports), 1)

    def test_exact_fixture_post_initial_extra_file_blocks_exec(self):
        def add_file(fixture):
            root = fixture.real(INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0])
            root.chmod(0o755)
            path = root / "post_initial_extra.py"
            path.write_bytes(b"VALUE = 91\n")
            path.chmod(0o444)
            root.chmod(0o555)

        self._assert_post_initial_exact_root_drift_blocked(
            add_file, "camera_runtime_install_admission_not_bound")

    def test_exact_fixture_same_bytes_new_inode_blocks_exec(self):
        def replace_same_bytes(fixture):
            target = fixture.real(
                INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0] +
                "/roslaunch/core.py")
            parent = target.parent
            parent.chmod(0o755)
            original = target.with_name("core.py.original")
            raw = target.read_bytes()
            original_inode = target.lstat().st_ino
            target.rename(original)
            target.write_bytes(raw)
            target.chmod(0o444)
            self.assertNotEqual(target.lstat().st_ino, original_inode)
            original.unlink()
            parent.chmod(0o555)

        self._assert_post_initial_exact_root_drift_blocked(
            replace_same_bytes,
            "camera_runtime_install_execution_closure_drift")

    def test_exact_fixture_post_initial_linklike_blocks_exec(self):
        def add_link(fixture):
            root = fixture.real(INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0])
            root.chmod(0o755)
            (root / "late_link.py").symlink_to("roslaunch/__init__.py")
            root.chmod(0o555)

        self._assert_post_initial_exact_root_drift_blocked(
            add_link, "camera_runtime_install_admission_not_bound")

    def test_exact_fixture_directory_mtime_drift_blocks_exec(self):
        def drift_mtime(fixture):
            directory = fixture.real(
                INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0] + "/roslaunch")
            before = directory.stat()
            os.utime(directory, ns=(
                before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))

        self._assert_post_initial_exact_root_drift_blocked(
            drift_mtime,
            "camera_runtime_install_execution_closure_drift")

    def test_exact_fixture_empty_directory_drift_blocks_exec(self):
        def add_empty_directory(fixture):
            root = fixture.real(INSTALL_ADMISSION.PYTHONPATH_ENTRIES[0])
            root.chmod(0o755)
            directory = root / "late_empty_namespace"
            directory.mkdir()
            directory.chmod(0o555)
            root.chmod(0o555)

        self._assert_post_initial_exact_root_drift_blocked(
            add_empty_directory,
            "camera_runtime_install_admission_not_bound")

    def test_second_admission_material_drift_is_rejected_by_role(self):
        mutations = {
            "python_target": lambda material: material[
                "roslaunch_admission"]["python_executable_target"].__setitem__(
                    "sha256", "1" * 64),
            "roslaunch": lambda material: (
                material["roslaunch_admission"]["executable"].__setitem__(
                    "sha256", "2" * 64),
                material["runtime_import_probe_stable_material"][
                    "aux_executable_closure"]["roslaunch"].__setitem__(
                        "sha256", "2" * 64)),
            "module_tree": lambda material: material[
                "roslaunch_admission"]["module_closure"]["roslaunch"].__setitem__(
                    "test_only", False),
            "package_xml": lambda material: material[
                "astra_resolution"]["package_xml"].__setitem__(
                    "test_only", False),
            "astra_launch": lambda material: material[
                "astra_resolution"]["launch"].__setitem__(
                    "sha256", "3" * 64),
            "astra_node": lambda material: material[
                "astra_resolution"]["node_executable"].__setitem__(
                    "test_only", False),
            "state_environment": lambda material: material[
                "clean_exec_environment_report"]["state_reports"].__setitem__(
                    "test_only", False),
            "clean_environment": lambda material: material[
                "clean_exec_environment"].__setitem__("ROS_IP", "127.0.0.2"),
            "authority": lambda material: material[
                "authority_identity"].__setitem__("sha256", "4" * 64),
            "runtime_import_probe": lambda material: material[
                "runtime_import_probe_stable_material"].__setitem__(
                    "executed_ids", ["different"]),
            "python_root_physical_digest": lambda material: material[
                "trusted_system_python_root_provenance"][0].__setitem__(
                    "inventory_physical_sha256", "5" * 64),
        }
        for role, mutate in mutations.items():
            first = copy.deepcopy(self.runtime_admission_report)
            second = copy.deepcopy(first)
            mutate(second["execution_closure_material"])
            self._refresh_report(second)
            reports = iter((first, second))
            called = []
            with self.subTest(role=role), self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "camera_runtime_install_execution_closure_drift"):
                self._execute(
                    lambda *_: called.append(True),
                    evaluator=lambda: copy.deepcopy(next(reports)))
            self.assertEqual(called, [])

    def test_python_target_swap_and_rewrite_are_rejected_before_exec(self):
        operations = {}

        def swap():
            self.python.parent.chmod(0o755)
            old = self.python.with_name("python3.10.original")
            self.python.rename(old)
            _write_executable(self.python, old.read_bytes())
            self.python.parent.chmod(0o555)

        def rewrite():
            raw = bytearray(self.python.read_bytes())
            raw[-2] ^= 1
            self.python.chmod(0o755)
            with self.python.open("r+b", buffering=0) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.python.chmod(0o555)

        operations["swap"] = swap
        operations["rewrite"] = rewrite
        for name, operation in operations.items():
            called = []
            with self.subTest(name=name), self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "python_executable_final_identity_mismatch"):
                self._execute(lambda *_: called.append(True), operation)
            self.assertEqual(called, [])

    def test_python_target_writable_or_wrong_hash_is_rejected(self):
        called = []
        self.python.chmod(0o755)
        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError, "python_executable_writable"):
            self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_non_inheritable_roslaunch_fd_is_rejected(self):
        called = []
        original = ATOMIC._open_validated_roslaunch_executable

        def make_non_inheritable(*args, **kwargs):
            fd, path, identity = original(*args, **kwargs)
            os.set_inheritable(fd, False)
            return fd, path, identity

        with mock.patch.object(
                ATOMIC, "_open_validated_roslaunch_executable",
                side_effect=make_non_inheritable), self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "roslaunch_executable_not_inheritable"):
            self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_execve_oserror_is_structured_fail_closed(self):
        def fail_exec(*unused):
            raise OSError("test-only exec failure")

        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError, "camera_only_execve_failed"):
            self._execute(fail_exec)

    def test_exec_argv_rejects_missing_flags_wrong_roots_and_path_fallback(self):
        roots = list(ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS)
        roots_arg = json.dumps(
            roots, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        base = [
            str(self.python), *ATOMIC.PYTHON_ISOLATION_ARGUMENTS,
            ATOMIC.ROSLAUNCH_FD_BOOTSTRAP, roots_arg,
            "/proc/self/fd/71", "/proc/self/fd/72",
            *ATOMIC.CAMERA_ONLY_OVERRIDES,
        ]
        cases = {
            "missing_flag": (
                base[:1] + base[2:], "camera_only_exec_python_flags_mismatch"),
            "wrong_roots": (
                base[:6] + [json.dumps(["/tmp/evil"])] + base[7:],
                "camera_only_exec_python_roots_mismatch"),
            "roslaunch_path": (
                base[:7] + [ATOMIC.ROSLAUNCH_EXECUTABLE] + base[8:],
                "camera_only_exec_not_using_roslaunch_fd"),
            "vendor_path": (
                base[:8] + [str(self.actual)] + base[9:],
                "camera_only_exec_not_using_sealed_fd"),
        }
        for name, (argv, code) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError, code):
                ATOMIC._validate_camera_exec_argv(
                    self.actual, self.python, 71, 72, roots, argv)

    def test_fixed_bootstrap_runs_only_roslaunch_fd_with_isolated_flags(self):
        roslaunch_script = self.root / "fake_roslaunch.py"
        roslaunch_script.write_text(
            "import json,sys\n"
            "print(json.dumps({'argv':sys.argv,'path':sys.path[:2],"
            "'isolated':sys.flags.isolated,'no_site':sys.flags.no_site,"
            "'dont_write_bytecode':sys.flags.dont_write_bytecode}))\n",
            encoding="utf-8")
        vendor = self.root / "sealed-vendor.launch"
        vendor.write_bytes(self.archive.read_bytes())
        roslaunch_fd = os.open(str(roslaunch_script), os.O_RDONLY)
        vendor_fd = os.open(str(vendor), os.O_RDONLY)
        try:
            os.set_inheritable(roslaunch_fd, True)
            os.set_inheritable(vendor_fd, True)
            roots = list(ATOMIC.TRUSTED_SYSTEM_PYTHON_ROOTS)
            completed = subprocess.run([
                sys.executable, *ATOMIC.PYTHON_ISOLATION_ARGUMENTS,
                ATOMIC.ROSLAUNCH_FD_BOOTSTRAP,
                json.dumps(roots, separators=(",", ":")),
                "/proc/self/fd/{}".format(roslaunch_fd),
                "/proc/self/fd/{}".format(vendor_fd),
                *ATOMIC.CAMERA_ONLY_OVERRIDES,
            ], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               text=True, pass_fds=(roslaunch_fd, vendor_fd), timeout=30)
        finally:
            os.close(roslaunch_fd)
            os.close(vendor_fd)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["argv"][0],
                         "/proc/self/fd/{}".format(roslaunch_fd))
        self.assertEqual(payload["argv"][1],
                         "/proc/self/fd/{}".format(vendor_fd))
        self.assertEqual(payload["path"], roots)
        self.assertEqual(
            [payload["isolated"], payload["no_site"],
             payload["dont_write_bytecode"]], [1, 1, 1])

    def test_rename_swap_after_preflight_is_rejected_before_fake_exec(self):
        called = []

        def swap():
            old = self.actual.with_name("original.launch")
            self.actual.rename(old)
            shutil.copyfile(self.archive, self.actual)

        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "actual_vendor_launch_final_identity_mismatch"):
            self._execute(lambda *_: called.append(True), swap)
        self.assertEqual(called, [])

    def test_path_drift_after_static_preflight_before_open_is_rejected(self):
        called = []
        original = ATOMIC.PREFLIGHT.evaluate_preflight

        def evaluate_then_drift(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertTrue(result["preflight_pass"], result["failures"])
            self.actual.write_bytes(self.actual.read_bytes() + b"\n")
            return result

        with mock.patch.object(
                ATOMIC.PREFLIGHT, "evaluate_preflight",
                side_effect=evaluate_then_drift):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "actual_vendor_launch_size_bytes_mismatch"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_symlink_swap_after_preflight_is_rejected_before_fake_exec(self):
        called = []

        def swap():
            old = self.actual.with_name("original.launch")
            self.actual.rename(old)
            self.actual.symlink_to(old.name)

        with self.assertRaises(ATOMIC.AtomicLaunchError):
            self._execute(lambda *_: called.append(True), swap)
        self.assertEqual(called, [])

    def test_same_inode_in_place_rewrite_is_rejected_before_fake_exec(self):
        called = []

        def rewrite():
            raw = bytearray(self.actual.read_bytes())
            raw[16] ^= 1
            with self.actual.open("r+b", buffering=0) as stream:
                stream.seek(0)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())

        with self.assertRaisesRegex(
                ATOMIC.AtomicLaunchError,
                "actual_vendor_launch_final_identity_mismatch"):
            self._execute(lambda *_: called.append(True), rewrite)
        self.assertEqual(called, [])

    def test_missing_required_seal_is_rejected_before_fake_exec(self):
        called = []

        def unsealed_memfd(raw):
            fd = os.memfd_create(
                "deliberately-unsealed-test",
                flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            ATOMIC._write_fd(fd, raw)
            os.set_inheritable(fd, True)
            return fd, {
                "proc_path": "/proc/self/fd/{}".format(fd),
                "size_bytes": len(raw),
                "sha256": PREFLIGHT._sha256(raw),
                "required_seal_mask": 0,
                "observed_seal_mask": 0,
                "inheritable": True,
            }

        with mock.patch.object(
                ATOMIC, "_make_sealed_memfd", side_effect=unsealed_memfd):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "sealed_memfd_required_seals_missing"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_preimport_fake_fcntl_is_not_accepted_as_seal_authority(self):
        launcher = ROOT / "audit_tools" / "ros1_camera_only_atomic_launcher.py"
        script = r'''
import importlib.machinery
import json
import runpy
import sys
import types
calls = {"fcntl": 0}
fake = types.ModuleType("fcntl")
fake.__spec__ = importlib.machinery.ModuleSpec(
    "fcntl", loader=None, origin="memory://fake-fcntl")
def invoked(*args, **kwargs):
    calls["fcntl"] += 1
    return 0
fake.fcntl = invoked
for name in ("F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE",
             "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL"):
    setattr(fake, name, 1)
sys.modules["fcntl"] = fake
try:
    runpy.run_path(sys.argv[1], run_name="_atomic_fcntl_probe")
except RuntimeError as error:
    print(json.dumps({"blocked": str(error), "calls": calls["fcntl"]}))
else:
    print(json.dumps({"blocked": None, "calls": calls["fcntl"]}))
'''
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, str(launcher)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["calls"], 0)
        self.assertIn("trusted_fcntl_", payload["blocked"])

    def test_fake_builtin_spec_fcntl_is_rejected_without_execution(self):
        launcher = ROOT / "audit_tools" / "ros1_camera_only_atomic_launcher.py"
        script = r'''
import importlib.machinery
import json
import runpy
import sys
import types
calls = {"fcntl": 0}
fake = types.ModuleType("fcntl")
fake.__spec__ = importlib.machinery.ModuleSpec(
    "fcntl", loader=importlib.machinery.BuiltinImporter, origin="built-in")
def forged(fd, op, value=0):
    calls["fcntl"] += 1
    return 0
fake.fcntl = forged
for name in ("F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE",
             "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL"):
    setattr(fake, name, 1)
sys.modules["fcntl"] = fake
try:
    runpy.run_path(sys.argv[1], run_name="_atomic_fcntl_probe")
except RuntimeError as error:
    print(json.dumps({
        "fake_calls": calls["fcntl"],
        "blocked": str(error),
        "ambient_unchanged": sys.modules.get("fcntl") is fake,
    }))
else:
    print(json.dumps({
        "fake_calls": calls["fcntl"],
        "blocked": None,
        "ambient_unchanged": sys.modules.get("fcntl") is fake,
    }))
'''
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, str(launcher)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["fake_calls"], 0)
        self.assertTrue(payload["ambient_unchanged"])
        self.assertEqual(
            payload["blocked"], "trusted_fcntl_ambient_identity_mismatch")

    def test_sealed_helper_report_drift_is_rejected_before_fake_exec(self):
        called = []
        original = ATOMIC._make_sealed_memfd

        def tampered_report(raw):
            fd, identity = original(raw)
            identity = dict(identity)
            identity["required_seal_mask"] = 0
            identity["observed_seal_mask"] = 0
            return fd, identity

        with mock.patch.object(
                ATOMIC, "_make_sealed_memfd", side_effect=tampered_report):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "sealed_memfd_report_identity_mismatch"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_non_inheritable_sealed_fd_is_rejected_before_fake_exec(self):
        called = []
        original = ATOMIC._make_sealed_memfd

        def make_non_inheritable(raw):
            fd, identity = original(raw)
            os.set_inheritable(fd, False)
            return fd, identity

        with mock.patch.object(
                ATOMIC, "_make_sealed_memfd",
                side_effect=make_non_inheritable):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "sealed_memfd_not_inheritable"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_inheritable_live_fd_is_rejected_before_fake_exec(self):
        called = []
        original = ATOMIC._open_validated_live_fd

        def make_live_inheritable(path, expected_identity):
            fd, raw, identity = original(path, expected_identity)
            os.set_inheritable(fd, True)
            return fd, raw, identity

        with mock.patch.object(
                ATOMIC, "_open_validated_live_fd",
                side_effect=make_live_inheritable):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "actual_vendor_launch_fd_inheritable"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])

    def test_cli_has_explicit_mode_and_rejects_arbitrary_roslaunch_args(self):
        parsed = ATOMIC.parse_args([
            "--mode", ATOMIC.MODE,
            "--actual-vendor-launch", str(self.actual),
        ])
        self.assertEqual(parsed.mode, ATOMIC.MODE)
        with self.assertRaises(ATOMIC.AtomicLaunchError) as raised:
            ATOMIC.parse_args([
                "--mode", ATOMIC.MODE,
                "--actual-vendor-launch", str(self.actual),
                "cmd_vel:=/evil",
            ])
        self.assertEqual(
            raised.exception.code,
            "atomic_cli_unexpected_positional_argument")
        with self.assertRaises(ATOMIC.AtomicLaunchError) as raised:
            ATOMIC.parse_args([
                "--actual-vendor-launch", str(self.actual),
            ])
        self.assertEqual(raised.exception.code, "atomic_cli_missing_argument:mode")

    def test_cli_argument_inventory_has_stable_fail_closed_codes(self):
        base = [
            "--mode", ATOMIC.MODE,
            "--actual-vendor-launch", str(self.actual),
        ]
        cases = (
            (base + ["--roslaunch-size-bytes", "123"],
             "atomic_cli_unknown_argument"),
            (base + ["unexpected"],
             "atomic_cli_unexpected_positional_argument"),
            (["--actual-vendor-launch", str(self.actual)],
             "atomic_cli_missing_argument:mode"),
            (["--mode", ATOMIC.MODE],
             "atomic_cli_missing_argument:actual_vendor_launch"),
            (["--mode"],
             "atomic_cli_missing_argument_value:mode"),
            (["--mode", ATOMIC.MODE, "--actual-vendor-launch"],
             "atomic_cli_missing_argument_value:actual_vendor_launch"),
            (base + ["--mode", ATOMIC.MODE],
             "atomic_cli_duplicate_argument:mode"),
            (base + ["--actual-vendor-launch", str(self.actual)],
             "atomic_cli_duplicate_argument:actual_vendor_launch"),
            (["--mode", "UNSAFE", "--actual-vendor-launch", str(self.actual)],
             "atomic_cli_argument_value_mismatch:mode"),
        )
        for argv, code in cases:
            with self.subTest(code=code), self.assertRaises(
                    ATOMIC.AtomicLaunchError) as raised:
                ATOMIC.parse_args(argv)
            self.assertEqual(raised.exception.code, code)

    def test_main_reports_cli_contract_failures_before_admission(self):
        cases = (
            (["--mode", ATOMIC.MODE,
              "--actual-vendor-launch", str(self.actual),
              "--roslaunch-sha256", "0" * 64],
             "atomic_cli_unknown_argument"),
            (["--actual-vendor-launch", str(self.actual)],
             "atomic_cli_missing_argument:mode"),
            (["--mode", ATOMIC.MODE, "--mode", ATOMIC.MODE,
              "--actual-vendor-launch", str(self.actual)],
             "atomic_cli_duplicate_argument:mode"),
        )
        for argv, code in cases:
            stderr = io.StringIO()
            with self.subTest(code=code), mock.patch.object(
                    ATOMIC.sys, "stderr", stderr), mock.patch.object(
                    ATOMIC, "_production_runtime_admission_evaluator"
                    ) as evaluator:
                self.assertEqual(ATOMIC.main(argv), 4)
            evaluator.assert_not_called()
            self.assertEqual(
                stderr.getvalue(),
                "ROS1_CAMERA_ONLY_ATOMIC_LAUNCH_BLOCKED:{}\n".format(code))

    def test_argv_helper_cannot_substitute_live_path_for_sealed_fd(self):
        called = []
        with mock.patch.object(
                ATOMIC, "_sealed_proc_path", return_value=str(self.actual)):
            with self.assertRaisesRegex(
                    ATOMIC.AtomicLaunchError,
                    "sealed_memfd_proc_path_identity_mismatch"):
                self._execute(lambda *_: called.append(True))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
