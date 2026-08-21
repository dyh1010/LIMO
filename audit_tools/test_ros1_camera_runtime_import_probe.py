"""Pure-software tests for the isolated camera-runtime import probe."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from audit_tools import ros1_camera_runtime_import_probe as PROBE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


@contextmanager
def _clean_parent_environment():
    safe_names = {
        "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "TEMP", "TMP",
        "TMPDIR", "WINDIR",
    }
    clean = {key: value for key, value in os.environ.items() if key in safe_names}
    with mock.patch.dict(os.environ, clean, clear=True):
        yield


class RuntimeImportFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="limo_ros1_runtime_import_fixture_")
        self.root = Path(self.temporary.name).resolve()
        self.noetic_prefix = self.root / "noetic"
        self.noetic_root = self.noetic_prefix / "lib" / "python3" / "dist-packages"
        self.system_root = self.root / "system" / "lib" / "python3" / "dist-packages"
        self.vendor_prefix = self.root / "vendor" / "install"
        self.package_root = self.vendor_prefix / "share" / "astra_camera"
        self.modules = {
            "catkin_pkg": self.system_root / "catkin_pkg" / "__init__.py",
            "rosgraph": self.noetic_root / "rosgraph" / "__init__.py",
            "roslaunch": self.noetic_root / "roslaunch" / "__init__.py",
            "roslib": self.noetic_root / "roslib" / "__init__.py",
            "rospkg": self.system_root / "rospkg" / "__init__.py",
            "yaml": self.system_root / "yaml" / "__init__.py",
        }
        self.assets = {
            "package_xml": self.package_root / "package.xml",
            "launch": self.package_root / "launch" / "dabai_u3.launch",
            "node_executable": (
                self.vendor_prefix / "lib" / "astra_camera" / "astra_camera_node"),
        }
        self.aux_executables = {
            "roslaunch": self.noetic_prefix / "bin" / "roslaunch"}
        self._build()

    def close(self) -> None:
        self.temporary.cleanup()

    def __enter__(self) -> "RuntimeImportFixture":
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()

    def _write(self, path: Path, raw: bytes, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)

    def _build(self) -> None:
        for name, path in self.modules.items():
            self._write(
                path,
                ("__version__ = 'fixture-" + name + "'\n").encode("ascii"))
        self._write(
            self.assets["package_xml"],
            b"<package><name>astra_camera</name></package>\n")
        self._write(
            self.assets["launch"],
            (b"<launch><node pkg=\"astra_camera\" "
             b"type=\"astra_camera_node\" name=\"camera\"/></launch>\n"))
        self._write(
            self.assets["node_executable"], b"#!/bin/sh\nexit 97\n", 0o755)
        self._write(
            self.aux_executables["roslaunch"],
            ("#!" + str(self.executable) + "\nraise SystemExit(98)\n").encode(
                "utf-8"),
            0o755)

    @property
    def executable(self) -> Path:
        return Path(sys.executable).resolve(strict=True)

    @property
    def probe_source(self) -> Path:
        return Path(PROBE.__file__).resolve(strict=True)

    def module_closure(self) -> dict:
        return {
            name: {
                "identity": _identity(path),
                "loader_kind": "SourceFileLoader",
                "expected_version": "fixture-" + name,
            }
            for name, path in self.modules.items()
        }

    def package_trees(self) -> dict:
        result = {}
        for name, module_path in self.modules.items():
            tree_id = name.split(".", 1)[0]
            if tree_id in result:
                continue
            root = module_path.parent
            files = {}
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    files[path.relative_to(root).as_posix()] = _identity(path)
            result[tree_id] = {"root_path": str(root.resolve()), "files": files}
        return result

    def python_root_inventories(self) -> dict:
        result = {}
        for role, root in (
                ("noetic", self.noetic_root),
                ("system", self.system_root)):
            directories = sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*") if path.is_dir())
            files = {
                path.relative_to(root).as_posix(): _identity(path)
                for path in sorted(root.rglob("*")) if path.is_file()
            }
            result[role] = {
                "root_path": str(root.resolve()),
                "directories": directories,
                "files": files,
            }
        return result

    def customization_inventory(self) -> dict:
        result = {}
        for role, root in (("noetic", self.noetic_root), ("system", self.system_root)):
            for path in sorted(root.iterdir()):
                if path.name in {"sitecustomize.py", "usercustomize.py"} or path.suffix == ".pth":
                    result[role + ":" + path.name] = _identity(path)
        return result

    def asset_identities(self) -> dict:
        return {role: _identity(path) for role, path in self.assets.items()}

    def kwargs(self, **updates: object) -> dict:
        values = {
            "admission_mode": PROBE.TEST_ONLY_MODE,
            "executable_identity": _identity(self.executable),
            "probe_source_identity": _identity(self.probe_source),
            "noetic_python_root": self.noetic_root,
            "system_python_root": self.system_root,
            "vendor_install_prefix": self.vendor_prefix,
            "module_closure": None,
            "package_trees": None,
            "python_root_inventories": None,
            "customization_inventory": None,
            "aux_executable_closure": None,
            "python_entry_path": self.executable,
            "python_entry_link_text": None,
            "astra_package_root": self.package_root,
            "astra_assets": self.asset_identities(),
            "timeout_sec": 30.0,
        }
        values.update(updates)
        if values["module_closure"] is None:
            values["module_closure"] = self.module_closure()
        if values["package_trees"] is None:
            values["package_trees"] = self.package_trees()
        if values["python_root_inventories"] is None:
            values["python_root_inventories"] = self.python_root_inventories()
        if values["customization_inventory"] is None:
            values["customization_inventory"] = self.customization_inventory()
        if values["aux_executable_closure"] is None:
            values["aux_executable_closure"] = {
                name: _identity(path)
                for name, path in self.aux_executables.items()}
        return values

    def run(self, **updates: object) -> dict:
        with _clean_parent_environment():
            return dict(PROBE.run_camera_runtime_import_probe(**self.kwargs(**updates)))


class CameraRuntimeImportProbeTest(unittest.TestCase):
    def test_unmanifested_python_root_artifact_classes_fail_before_child(self) -> None:
        cases = (
            ("top_level_py", "file", "late_unmanifested.py"),
            ("package", "package", "late_unmanifested/__init__.py"),
            (
                "extension", "file",
                "late_unmanifested" + PROBE.importlib.machinery.EXTENSION_SUFFIXES[0],
            ),
        )
        for name, kind, relative in cases:
            with self.subTest(name=name), RuntimeImportFixture() as fixture:
                inventory = fixture.python_root_inventories()
                target = fixture.noetic_root / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"unmanifested-loadable-artifact\n")
                calls = []

                def fake_runner(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError("child must not execute")

                report = fixture.run(
                    python_root_inventories=inventory,
                    subprocess_runner=fake_runner)
            expected = (
                "probe_python_root_inventory_directory_set_mismatch:noetic"
                if kind == "package"
                else "probe_python_root_inventory_file_set_mismatch:noetic")
            self.assertIn(expected, report["failures"])
            self.assertEqual([], calls)

    def test_python_root_inventory_drift_after_child_is_rejected(self) -> None:
        with RuntimeImportFixture() as fixture:
            calls = []

            def mutate_after_child(*args, **kwargs):
                completed = subprocess.run(*args, **kwargs)
                calls.append(tuple(args[0]))
                (fixture.system_root / "late_after_child.py").write_bytes(
                    b"VALUE = 73\n")
                return completed

            report = fixture.run(subprocess_runner=mutate_after_child)
        self.assertEqual(1, len(calls))
        self.assertIn(
            "probe_python_root_inventory_drift:system", report["failures"])
        self.assertFalse(report["algorithm_validated"])

    def test_unmanifested_python_root_linklike_fails_before_child(self) -> None:
        with RuntimeImportFixture() as fixture:
            inventory = fixture.python_root_inventories()
            target = fixture.noetic_root / "real_late.py"
            target.write_bytes(b"VALUE = 73\n")
            link = fixture.noetic_root / "late_link.py"
            try:
                link.symlink_to(target.name)
            except (OSError, NotImplementedError) as error:
                self.skipTest("symlinks unavailable: " + str(error))
            calls = []

            def fake_runner(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("child must not execute")

            report = fixture.run(
                python_root_inventories=inventory,
                subprocess_runner=fake_runner)
        self.assertTrue(any(
            item.startswith(
                "probe_python_root_inventory:noetic:file:late_link.py:linklike")
            for item in report["failures"]), report["failures"])
        self.assertEqual([], calls)

    def test_actual_isolated_test_only_probe_imports_complete_closure(self) -> None:
        with RuntimeImportFixture() as fixture:
            report = fixture.run()
        self.assertEqual([], report["failures"])
        self.assertTrue(report["algorithm_validated"])
        self.assertTrue(report["validator_unit_test_pass"])
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["runtime_import_probe_pass"])
        self.assertFalse(report["formal_consumer"])
        self.assertFalse(report["field_evidence_admitted"])
        self.assertFalse(report["delivery_ready"])
        self.assertEqual(report["expected_ids"], report["executed_ids"])
        self.assertEqual(
            [str(fixture.executable), "-I", "-S", "-B"], report["argv"][:4])
        marker = report["child_marker"]
        self.assertEqual(sorted(PROBE.REQUIRED_MODULES), marker["loaded_nonstdlib_module_ids"])
        self.assertEqual(set(PROBE.REQUIRED_MODULES), set(marker["module_provenance"]))
        self.assertEqual(set(PROBE.ASSET_ROLES), set(marker["astra_asset_provenance"]))
        self.assertTrue(report["parent_environment_restored"])

    def test_production_is_unanchored_and_rejects_runner_injection(self) -> None:
        calls = []

        def fake_runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner must not execute")

        with _clean_parent_environment():
            plain = PROBE.run_camera_runtime_import_probe(
                admission_mode=PROBE.PRODUCTION_MODE)
            injected = PROBE.run_camera_runtime_import_probe(
                admission_mode=PROBE.PRODUCTION_MODE,
                subprocess_runner=fake_runner)
            borrowed = PROBE.run_camera_runtime_import_probe(
                admission_mode=PROBE.PRODUCTION_MODE,
                executable_identity={
                    "path": "/old/authority/python3.8",
                    "size_bytes": 1,
                    "sha256": "0" * 64,
                })
        self.assertIn(
            "production_runtime_import_probe_not_anchored", plain["failures"])
        self.assertIn(
            "probe_production_runner_injection_forbidden", injected["failures"])
        self.assertIn(
            "probe_production_caller_spec_forbidden", borrowed["failures"])
        self.assertEqual([], calls)
        for report in (plain, injected, borrowed):
            self.assertFalse(report["validated_pass"])
            self.assertFalse(report["delivery_ready"])

    def test_missing_module_fails_before_child_execution(self) -> None:
        with RuntimeImportFixture() as fixture:
            closure = fixture.module_closure()
            trees = fixture.package_trees()
            fixture.modules["rosgraph"].unlink()
            calls = []

            def fake_runner(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("runner must not execute")

            report = fixture.run(
                module_closure=closure, package_trees=trees,
                subprocess_runner=fake_runner)
        self.assertTrue(any(
            value.startswith("probe_module_artifact:rosgraph:missing")
            for value in report["failures"]))
        self.assertEqual([], calls)

    def test_module_raise_after_version_assignment_is_detected_by_real_import(self) -> None:
        with RuntimeImportFixture() as fixture:
            fixture.modules["roslaunch"].write_text(
                "__version__ = 'fixture-roslaunch'\n"
                "raise RuntimeError('fresh import must fail')\n",
                encoding="utf-8")
            report = fixture.run()
        self.assertFalse(report["algorithm_validated"])
        self.assertIn("probe_child_nonzero_exit", report["failures"])
        self.assertTrue(any(
            "child_module_import_failed:roslaunch:RuntimeError" in value
            for value in report["failures"]))

    def test_module_version_is_cross_checked_against_fixed_policy(self) -> None:
        with RuntimeImportFixture() as fixture:
            closure = fixture.module_closure()
            closure["roslaunch"]["expected_version"] = "wrong-version"
            report = fixture.run(module_closure=closure)
        self.assertIn("probe_child_nonzero_exit", report["failures"])
        self.assertTrue(any(
            "child_module_version_mismatch:roslaunch" in value
            for value in report["failures"]))

    def test_extension_loader_kind_is_supported_but_suffix_bound(self) -> None:
        import _ctypes

        origin = Path(_ctypes.__file__).resolve(strict=True)
        provenance = PROBE._module_provenance(
            _ctypes, (origin.parent,), "_ctypes", "ExtensionFileLoader")
        self.assertEqual(_identity(origin), PROBE._identity(provenance))
        invalid = {
            "identity": _identity(Path(PROBE.__file__).resolve()),
            "loader_kind": "ExtensionFileLoader",
            "expected_version": None,
        }
        self.assertFalse(PROBE._valid_module_spec(invalid))

    def test_child_binds_running_sys_executable_not_only_request_file(self) -> None:
        with RuntimeImportFixture() as fixture, _clean_parent_environment():
            kwargs = fixture.kwargs()
            fake_python = fixture.root / "python3.99"
            fake_python.write_bytes(b"fixture-executable\n")
            fake_python.chmod(0o755)
            fixture.aux_executables["roslaunch"].write_text(
                "#!" + str(fake_python) + "\nraise SystemExit(98)\n",
                encoding="utf-8")
            kwargs["executable_identity"] = _identity(fake_python)
            kwargs["python_entry_path"] = fake_python
            kwargs["aux_executable_closure"] = {
                "roslaunch": _identity(fixture.aux_executables["roslaunch"])}
            spec = {
                key: kwargs[key] for key in (
                    "executable_identity", "probe_source_identity",
                    "noetic_python_root", "system_python_root",
                    "vendor_install_prefix", "module_closure",
                    "package_trees", "python_root_inventories",
                    "customization_inventory",
                    "aux_executable_closure", "python_entry_path",
                    "python_entry_link_text", "astra_package_root",
                    "astra_assets")}
            spec["noetic_python_root"] = str(spec["noetic_python_root"])
            spec["system_python_root"] = str(spec["system_python_root"])
            spec["vendor_install_prefix"] = str(spec["vendor_install_prefix"])
            spec["python_entry_path"] = str(spec["python_entry_path"])
            spec["astra_package_root"] = str(spec["astra_package_root"])
            validated = PROBE._validate_inputs(spec, production=False)
            request = dict(PROBE._request(
                spec, validated, PROBE.TEST_ONLY_MODE))
            request_path = fixture.root / "child_request.json"
            request_path.write_bytes(PROBE._json_bytes(request))
            marker, exit_code = PROBE._child_execute(request_path)
        self.assertEqual(1, exit_code)
        self.assertIn(
            "child_sys_executable_identity_mismatch", marker["failures"])

    def test_wrong_import_origin_is_rejected(self) -> None:
        with RuntimeImportFixture() as fixture:
            shadow = fixture.noetic_root / "rospkg" / "__init__.py"
            fixture._write(shadow, b"__version__ = 'shadow'\n")
            report = fixture.run()
        self.assertFalse(report["algorithm_validated"])
        self.assertTrue(any(
            "child_module_identity_mismatch:rospkg" in value
            or "child_module_origin_invalid:rospkg" in value
            for value in report["failures"]))

    def test_source_devel_or_build_roots_are_rejected_before_spawn(self) -> None:
        with RuntimeImportFixture() as fixture:
            devel_root = fixture.root / "devel" / "lib" / "python3" / "dist-packages"
            shutil.copytree(fixture.noetic_root, devel_root)
            closure = fixture.module_closure()
            for name in ("rosgraph", "roslaunch", "roslib"):
                closure[name]["identity"] = _identity(
                    devel_root / name / "__init__.py")
            calls = []

            def fake_runner(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("runner must not execute")

            report = fixture.run(
                noetic_python_root=devel_root,
                module_closure=closure,
                subprocess_runner=fake_runner)
        self.assertIn("probe_noetic_python_root_invalid", report["failures"])
        self.assertEqual([], calls)

    def test_roslaunch_aux_executable_is_mandatory_and_prefix_bound(self) -> None:
        with RuntimeImportFixture() as fixture:
            missing = fixture.run(aux_executable_closure={})
            extra = fixture.run(aux_executable_closure={
                "roslaunch": _identity(fixture.aux_executables["roslaunch"]),
                "python_helper": _identity(fixture.executable),
            })
            wrong_path = fixture.root / "system" / "bin" / "roslaunch"
            fixture._write(wrong_path, b"#!/bin/sh\nexit 99\n", 0o755)
            wrong = fixture.run(
                aux_executable_closure={"roslaunch": _identity(wrong_path)})
        self.assertIn(
            "probe_aux_executable_closure_schema_invalid", missing["failures"])
        self.assertIn(
            "probe_aux_executable_closure_schema_invalid", extra["failures"])
        self.assertIn("probe_aux_roslaunch_path_mismatch", wrong["failures"])

    def test_roslaunch_aux_shebang_is_bound_to_python_entry(self) -> None:
        with RuntimeImportFixture() as fixture:
            fixture.aux_executables["roslaunch"].write_text(
                "#!/usr/bin/env python3\nraise SystemExit(98)\n",
                encoding="utf-8")
            report = fixture.run()
        self.assertIn(
            "probe_aux_roslaunch_shebang_mismatch", report["failures"])

    def test_external_production_spec_is_strict_and_omits_probe_source(self) -> None:
        with RuntimeImportFixture() as fixture:
            kwargs = fixture.kwargs()
            payload = {
                "schema_version": PROBE.SCHEMA_VERSION,
                "marker": PROBE.PRODUCTION_SPEC_MARKER,
                "executable_identity": kwargs["executable_identity"],
                "noetic_python_root": str(kwargs["noetic_python_root"]),
                "system_python_root": str(kwargs["system_python_root"]),
                "vendor_install_prefix": str(kwargs["vendor_install_prefix"]),
                "module_closure": kwargs["module_closure"],
                "package_trees": kwargs["package_trees"],
                "python_root_inventories": kwargs["python_root_inventories"],
                "customization_inventory": kwargs["customization_inventory"],
                "aux_executable_closure": kwargs["aux_executable_closure"],
                "python_entry_path": str(kwargs["python_entry_path"]),
                "python_entry_link_text": kwargs["python_entry_link_text"],
                "astra_package_root": str(kwargs["astra_package_root"]),
                "astra_assets": kwargs["astra_assets"],
            }
            trust_root = fixture.root / "production_spec_trust"
            trust_root.mkdir()
            path = trust_root / "production_spec.json"
            raw = PROBE._json_bytes(payload)
            path.write_bytes(raw)
            path.chmod(0o444)
            trust_root.chmod(0o555)
            source_identity = _identity(Path(PROBE.__file__).resolve())
            owner_uid = int(os.getuid()) if hasattr(os, "getuid") else 0
            loaded = PROBE._load_external_production_spec(
                path, len(raw), hashlib.sha256(raw).hexdigest(), trust_root,
                owner_uid, source_identity)
            self.assertEqual(source_identity, loaded["probe_source_identity"])
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_spec_file_policy_invalid"):
                PROBE._load_external_production_spec(
                    path, len(raw), hashlib.sha256(raw).hexdigest(), trust_root,
                    owner_uid + 1, source_identity)
            trust_root.chmod(0o755)
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_spec_file_policy_invalid"):
                PROBE._load_external_production_spec(
                    path, len(raw), hashlib.sha256(raw).hexdigest(), trust_root,
                    owner_uid, source_identity)
            trust_root.chmod(0o555)
            path.chmod(0o644)
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_spec_file_policy_invalid"):
                PROBE._load_external_production_spec(
                    path, len(raw), hashlib.sha256(raw).hexdigest(), trust_root,
                    owner_uid, source_identity)
            path.chmod(0o644)
            trust_root.chmod(0o755)
            payload["probe_source_identity"] = source_identity
            raw = PROBE._json_bytes(payload)
            path.write_bytes(raw)
            path.chmod(0o444)
            trust_root.chmod(0o555)
            with self.assertRaisesRegex(
                    PROBE.ProbeError, "probe_production_spec_schema_invalid"):
                PROBE._load_external_production_spec(
                    path, len(raw), hashlib.sha256(raw).hexdigest(),
                    trust_root, owner_uid, source_identity)
            trust_root.chmod(0o755)
            path.chmod(0o644)

    def test_production_parent_attestation_rejects_flags_customization_and_meta_path(self) -> None:
        bad_flags = types.SimpleNamespace(
            isolated=0, no_site=1)
        with mock.patch.object(PROBE.sys, "flags", bad_flags), \
                mock.patch.object(PROBE.sys, "dont_write_bytecode", True):
            with self.assertRaisesRegex(
                    PROBE.ProbeError, "probe_production_parent_flags_invalid"):
                PROBE._attest_production_parent()
        clean_flags = types.SimpleNamespace(
            isolated=1, no_site=1)
        with mock.patch.object(PROBE.sys, "flags", clean_flags), \
                mock.patch.object(PROBE.sys, "dont_write_bytecode", True), \
                mock.patch.dict(PROBE.sys.modules, {
                    "sitecustomize": types.ModuleType("sitecustomize")}, clear=False):
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_parent_customization_loaded"):
                PROBE._attest_production_parent()
        with mock.patch.object(PROBE.sys, "flags", clean_flags), \
                mock.patch.object(PROBE.sys, "dont_write_bytecode", True), \
                mock.patch.object(PROBE.sys, "meta_path", [object()]), \
                mock.patch.object(PROBE.sys, "modules", {
                    key: value for key, value in PROBE.sys.modules.items()
                    if key not in {"sitecustomize", "usercustomize"}}):
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_parent_meta_path_untrusted"):
                PROBE._attest_production_parent()
        calls = []
        fake_json = types.ModuleType("json")
        fake_json.__spec__ = types.SimpleNamespace(
            origin="memory://fake-json", loader=object())
        fake_json.loads = lambda *args, **kwargs: calls.append((args, kwargs))
        with mock.patch.object(PROBE.sys, "flags", clean_flags), \
                mock.patch.object(PROBE.sys, "dont_write_bytecode", True), \
                mock.patch.object(PROBE, "json", fake_json), \
                mock.patch.object(PROBE.sys, "meta_path", [
                    PROBE.importlib.machinery.BuiltinImporter,
                    PROBE.importlib.machinery.FrozenImporter,
                    PROBE.importlib.machinery.PathFinder]), \
                mock.patch.object(PROBE.sys, "modules", {
                    key: value for key, value in PROBE.sys.modules.items()
                    if key not in {"sitecustomize", "usercustomize"}}):
            with self.assertRaisesRegex(
                    PROBE.ProbeError,
                    "probe_production_parent_stdlib_identity_invalid:json"):
                PROBE._attest_production_parent()
        self.assertEqual([], calls)

    def test_root_owned_modes_allow_0755_0644_only_for_non_root_runtime(self) -> None:
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
        with mock.patch.object(PROBE.os, "geteuid", return_value=1000):
            self.assertTrue(PROBE._immutable_execution_mode_safe(directory, 0))
            self.assertTrue(PROBE._immutable_execution_mode_safe(regular, 0))
            self.assertFalse(
                PROBE._immutable_execution_mode_safe(group_writable, 0))
            self.assertFalse(
                PROBE._immutable_execution_mode_safe(world_writable, 0))
            self.assertFalse(
                PROBE._immutable_execution_mode_safe(current_owner, 1000))

    def test_production_execution_identity_rejects_root_and_mismatch(self) -> None:
        for name, uid, euid in (
                ("root", 0, 0), ("mismatch", 1000, 1001)):
            with self.subTest(name=name), \
                    mock.patch.object(PROBE.os, "getuid", return_value=uid), \
                    mock.patch.object(PROBE.os, "geteuid", return_value=euid), \
                    self.assertRaisesRegex(
                        PROBE.ProbeError,
                        "probe_production_execution_identity_invalid"):
                PROBE._attest_production_execution_identity()

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "getuid")
        and hasattr(os, "geteuid"),
        "POSIX ownership identity is required")
    def test_fresh_isolated_parent_accepts_real_root_owned_stdlib(self) -> None:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("positive production parent requires non-root euid")
        script = (
            "import runpy,sys;"
            "ns=runpy.run_path(sys.argv[1],run_name='_probe_mode_test');"
            "ns['_attest_production_parent']();"
            "print('ROOT_OWNED_STDLIB_MODE_PASS')")
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script,
             str(Path(PROBE.__file__).resolve())],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(),
                         "ROOT_OWNED_STDLIB_MODE_PASS")

    def test_symlink_and_hardlink_module_artifacts_fail_closed(self) -> None:
        with self.subTest("hardlink"):
            with RuntimeImportFixture() as fixture:
                path = fixture.modules["roslib"]
                raw = path.read_bytes()
                other = path.with_name("hardlink_source.py")
                other.write_bytes(raw)
                path.unlink()
                os.link(str(other), str(path))
                closure = fixture.module_closure()
                report = fixture.run(module_closure=closure)
            self.assertTrue(any(
                value.startswith(
                    "probe_python_root_inventory:noetic:file:"
                    "roslib/__init__.py:hardlink")
                for value in report["failures"]))

        with self.subTest("symlink"):
            with RuntimeImportFixture() as fixture:
                path = fixture.modules["yaml"]
                closure = fixture.module_closure()
                trees = fixture.package_trees()
                target = path.with_name("real_init.py")
                target.write_bytes(path.read_bytes())
                path.unlink()
                try:
                    path.symlink_to(target.name)
                except (OSError, NotImplementedError) as error:
                    self.skipTest("symlinks unavailable: " + str(error))
                report = fixture.run(
                    module_closure=closure, package_trees=trees)
            self.assertTrue(any(
                value.startswith(
                    "probe_python_root_inventory:system:file:"
                    "yaml/__init__.py:linklike")
                for value in report["failures"]))

    def test_undeclared_customization_files_are_rejected_without_execution(self) -> None:
        for filename in ("sitecustomize.py", "usercustomize.py", "attack.pth"):
            with self.subTest(filename=filename), RuntimeImportFixture() as fixture:
                inventory = fixture.customization_inventory()
                calls = []

                def fake_runner(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError("runner must not execute")

                marker = fixture.noetic_root / filename
                marker.write_text(
                    "raise RuntimeError('customization must never execute')\n",
                    encoding="utf-8")
                report = fixture.run(
                    customization_inventory=inventory,
                    subprocess_runner=fake_runner)
            self.assertIn(
                "probe_customization_inventory_set_mismatch", report["failures"])
            self.assertEqual([], calls)

    def test_production_customization_inventory_must_be_empty(self) -> None:
        with self.assertRaisesRegex(
                PROBE.ProbeError,
                "probe_production_customization_inventory_not_empty"):
            PROBE._enforce_customization_policy(
                {"noetic:sitecustomize.py": {"identity": "irrelevant"}},
                production=True)
        PROBE._enforce_customization_policy({}, production=True)

    def test_undeclared_roslaunch_core_file_is_rejected_before_import(self) -> None:
        with RuntimeImportFixture() as fixture:
            trees = fixture.package_trees()
            calls = []

            def fake_runner(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("runner must not execute")

            fixture._write(
                fixture.modules["roslaunch"].parent / "core.py",
                b"raise RuntimeError('undeclared file must not execute')\n")
            report = fixture.run(
                package_trees=trees, subprocess_runner=fake_runner)
        self.assertIn(
            "probe_package_tree_file_set_mismatch:roslaunch",
            report["failures"])
        self.assertEqual([], calls)

    def test_actual_loaded_module_set_must_equal_declared_closure(self) -> None:
        with RuntimeImportFixture() as fixture:
            fixture._write(
                fixture.modules["roslaunch"].parent / "core.py",
                b"VALUE = 1\n")
            fixture.modules["roslaunch"].write_text(
                "from . import core\n"
                "__version__ = 'fixture-roslaunch'\n",
                encoding="utf-8")
            report = fixture.run()
        self.assertIn("probe_child_nonzero_exit", report["failures"])
        self.assertTrue(any(
            "child_loaded_module_closure_incomplete" in value
            for value in report["failures"]))

    def test_ambient_python_ros_and_ld_injection_fail_before_runner(self) -> None:
        for key in (
                "PYTHONPATH", "PYTHONHOME", "ROS_PACKAGE_PATH",
                "ROS_MASTER_URI", "LD_LIBRARY_PATH", "LD_PRELOAD"):
            with self.subTest(key=key), RuntimeImportFixture() as fixture:
                calls = []

                def fake_runner(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError("runner must not execute")

                safe_names = {
                    "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT",
                    "TEMP", "TMP", "TMPDIR", "WINDIR",
                }
                clean = {
                    name: value for name, value in os.environ.items()
                    if name in safe_names}
                clean[key] = "/tmp/attacker"
                with mock.patch.dict(os.environ, clean, clear=True):
                    report = PROBE.run_camera_runtime_import_probe(
                        **fixture.kwargs(subprocess_runner=fake_runner))
                self.assertIn(
                    "probe_ambient_environment_forbidden:" + key,
                    report["failures"])
                self.assertEqual([], calls)

    def test_missing_multiple_and_nonzero_child_markers_fail_closed(self) -> None:
        def missing(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        def multiple(argv, **kwargs):
            raw = PROBE.CLI_MARKER + "{}\n"
            return subprocess.CompletedProcess(argv, 0, stdout=raw + raw, stderr="")

        def nonzero(argv, **kwargs):
            completed = subprocess.run(argv, **kwargs)
            return subprocess.CompletedProcess(
                argv, 9, stdout=completed.stdout, stderr=completed.stderr)

        for name, runner, code in (
                ("missing", missing, "probe_child_marker_count_invalid"),
                ("multiple", multiple, "probe_child_marker_count_invalid"),
                ("nonzero", nonzero, "probe_child_nonzero_exit")):
            with self.subTest(name=name), RuntimeImportFixture() as fixture:
                report = fixture.run(subprocess_runner=runner)
            self.assertIn(code, report["failures"])
            self.assertFalse(report["validator_unit_test_pass"])

    def test_complete_executed_id_set_is_parent_recomputed(self) -> None:
        def tamper(argv, **kwargs):
            completed = subprocess.run(argv, **kwargs)
            line = completed.stdout.strip()
            marker = json.loads(line[len(PROBE.CLI_MARKER):])
            marker["executed_ids"] = marker["executed_ids"][:-1]
            stdout = (
                PROBE.CLI_MARKER
                + json.dumps(marker, sort_keys=True, separators=(",", ":"))
                + "\n")
            return subprocess.CompletedProcess(
                argv, completed.returncode, stdout=stdout, stderr=completed.stderr)

        with RuntimeImportFixture() as fixture:
            report = fixture.run(subprocess_runner=tamper)
        self.assertIn(
            "probe_child_marker_semantic_mismatch:executed_ids",
            report["failures"])

    def test_marker_parser_rejects_duplicate_nonfinite_and_extra_output(self) -> None:
        cases = {
            "duplicate": (
                PROBE.CLI_MARKER + '{"marker":"a","marker":"b"}\n', ""),
            "nonfinite": (PROBE.CLI_MARKER + '{"value":NaN}\n', ""),
            "extra_stdout": ("noise\n" + PROBE.CLI_MARKER + "{}\n", ""),
            "stderr": (PROBE.CLI_MARKER + "{}\n", "noise"),
        }
        for name, (stdout, stderr) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(PROBE.ProbeError):
                    PROBE._parse_child_marker(stdout, stderr)

    def test_cli_is_one_marker_nonzero_and_production_blocked(self) -> None:
        module = Path(PROBE.__file__).resolve(strict=True)
        executable = Path(sys.executable).resolve(strict=True)
        clean = {
            key: value for key, value in os.environ.items()
            if key in {
                "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT",
                "TEMP", "TMP", "TMPDIR", "WINDIR"}
        }
        completed = subprocess.run(
            [str(executable), "-I", "-S", "-B", str(module)],
            cwd=str(module.parent), env=clean, capture_output=True, text=True,
            encoding="utf-8", errors="strict", timeout=30.0, check=False)
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        self.assertEqual(1, len(completed.stdout.splitlines()))
        self.assertTrue(completed.stdout.startswith(PROBE.CLI_MARKER))
        report = json.loads(completed.stdout[len(PROBE.CLI_MARKER):])
        self.assertIn(
            "production_runtime_import_probe_not_anchored", report["failures"])
        self.assertFalse(report["validated_pass"])
        self.assertFalse(report["delivery_ready"])


if __name__ == "__main__":
    unittest.main()
