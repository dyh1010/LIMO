"""Pure-software tests for the isolated ROS1 rosbag reader probe."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from limo_cleanup_ros1_perception import rosbag1_isolated_probe as probe


def _identity(path):
    path = Path(path).resolve(strict=True)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_executable(path, payload=b"anchored-python-target\n"):
    path = Path(path)
    path.write_bytes(payload)
    path.chmod(path.stat().st_mode | 0o111)
    return path


class _AmbientFakeFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.calls = 0

    def find_spec(self, fullname, path=None, target=None):
        del path, target
        if fullname == "rosbag" or fullname.startswith("rosbag."):
            self.calls += 1
        return None


class IsolatedRosbagProbeTest(unittest.TestCase):
    def _symlink_or_skip(self, link_path, target):
        try:
            Path(link_path).symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.skipTest("symlink creation unavailable: {}".format(error))

    def _fixture(self, root):
        root = Path(root)
        probe_root = root / "probe-package"
        probe_root.mkdir()
        probe_path = probe_root / "rosbag1_isolated_probe.py"
        probe_path.write_bytes(Path(probe.__file__).read_bytes())
        probe_spec = importlib.util.spec_from_file_location(
            "_test_exact_rosbag1_isolated_probe", probe_path)
        probe_module = importlib.util.module_from_spec(probe_spec)
        probe_spec.loader.exec_module(probe_module)
        prefix = root / "noetic"
        python_root = prefix / "lib" / "python3" / "dist-packages"
        package = python_root / "rosbag"
        package.mkdir(parents=True)
        rosbag_source = '''
from .bag import Bag
'''.lstrip()
        rosbag_bag_source = '''
import json

class _Connection:
    def __init__(self, value):
        self.id = value["id"]
        self.topic = value["topic"]
        self.datatype = value["datatype"]
        self.md5sum = value["md5sum"]
        self.header = value["header"]

class _Stamp:
    def __init__(self, value):
        self.value = value
    def to_nsec(self):
        return self.value

class _MessageType:
    pass

class Bag:
    version = 200
    def __init__(self, path, mode="r", allow_unindexed=False):
        del mode, allow_unindexed
        raw = open(path, "rb").read().split(b"\\n", 1)[1]
        self.value = json.loads(raw.decode("utf-8"))
    def _get_connections(self):
        return [_Connection(item) for item in self.value["connections"]]
    def read_messages(self, raw=True, return_connection_header=True):
        del raw, return_connection_header
        for item in self.value["messages"]:
            raw_message = (
                item["datatype"], bytes.fromhex(item["payload_hex"]),
                item["md5sum"], 0, _MessageType)
            yield (
                item["topic"], raw_message, _Stamp(item["stamp_ns"]),
                item["header"])
    def close(self):
        pass
'''.lstrip()
        rosbag_path = package / "__init__.py"
        rosbag_path.write_text(rosbag_source, encoding="utf-8")
        (package / "bag.py").write_text(rosbag_bag_source, encoding="utf-8")

        indexer_source = '''
import json

FORMAL_CAMERA_ONLY_MODE = "formal_camera_only"

def load_formal_manifest(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.loads(stream.read())

class Rosbag1Reader:
    def __init__(self, path, diagnostic=False):
        self.path = path
        self.diagnostic = diagnostic
    def read(self):
        import rosbag
        bag = rosbag.Bag(str(self.path), mode="r", allow_unindexed=False)
        try:
            connections = []
            signature = {}
            for info in bag._get_connections():
                row = {
                    "connection_id": info.id,
                    "topic": info.topic,
                    "type": info.datatype,
                    "md5sum": info.md5sum,
                    "connection_header": dict(info.header),
                }
                connections.append(row)
                signature[(info.topic, info.datatype, info.md5sum)] = info.id
            messages = []
            for topic, raw, stamp, header in bag.read_messages(
                    raw=True, return_connection_header=True):
                datatype, data, md5sum, _position, _pytype = raw
                messages.append({
                    "connection_id": signature[(topic, datatype, md5sum)],
                    "record_timestamp_ns": stamp.to_nsec(),
                    "serialized_payload": data,
                    "decoded": {"header": {"stamp_ns": stamp.to_nsec()}},
                    "connection_header": dict(header),
                })
            return connections, messages
        finally:
            bag.close()

def inspect_records(connections, messages, capture_id, scene, manifest,
                    source_capture, mode):
    del manifest, mode
    return {
        "schema_version": 1,
        "report_kind": "formal_rgbd_raw_capture_index",
        "formal_acceptance": True,
        "delivery_ready": False,
        "source_capture": source_capture,
        "capture_id": capture_id,
        "scene": scene,
        "connection_count": len(connections),
        "message_count": len(messages),
    }
'''.lstrip()
        indexer_path = probe_root / "rosbag1_rgbd_indexer.py"
        indexer_path.write_text(indexer_source, encoding="utf-8")
        manifest_path = root / "formal_manifest.json"
        manifest_path.write_text(
            json.dumps({"manifest_id": "test-formal-v1"}), encoding="utf-8")
        bag_path = root / "scene.bag"
        bag_payload = {
            "connections": [{
                "id": 1,
                "topic": "/camera/color/image_raw",
                "datatype": "sensor_msgs/Image",
                "md5sum": "image-md5",
                "header": {"callerid": "/camera/camera", "latching": "0"},
            }],
            "messages": [{
                "topic": "/camera/color/image_raw",
                "datatype": "sensor_msgs/Image",
                "md5sum": "image-md5",
                "payload_hex": "000102ff",
                "stamp_ns": 123456789,
                "header": {"callerid": "/camera/camera", "latching": "0"},
            }],
        }
        bag_path.write_bytes(
            probe_module.ROSBAG1_V2_MAGIC
            + json.dumps(bag_payload, sort_keys=True).encode("utf-8"))
        return {
            "prefix": prefix,
            "rosbag": rosbag_path,
            "rosbag_bag": package / "bag.py",
            "indexer": indexer_path,
            "manifest": manifest_path,
            "bag": bag_path,
            "output": root / "probe-output.json",
            "probe": probe_module,
            "probe_path": probe_path,
        }

    def _run(
            self, fixture, *, capture_id="capture-1", scene="background",
            output_path=None):
        module = fixture["probe"]
        output = fixture["output"] if output_path is None else Path(output_path)
        return module.run_isolated_rosbag_probe(
            fixture["bag"],
            _identity(fixture["bag"]),
            fixture["prefix"],
            _identity(fixture["rosbag"]),
            {
                "rosbag": _identity(fixture["rosbag"]),
                "rosbag.bag": _identity(fixture["rosbag_bag"]),
            },
            _identity(fixture["indexer"]),
            fixture["manifest"],
            _identity(fixture["manifest"]),
            _identity(fixture["probe_path"]),
            _identity(Path(sys.executable)),
            capture_id,
            scene,
            output,
            admission_mode="test_only",
            timeout_sec=30.0,
        )

    def _request_for_result(self, fixture, result):
        module = fixture["probe"]
        return {
            "schema_version": 1,
            "marker": module.REQUEST_MARKER,
            "request_id": result["child_marker"]["request_id"],
            "bag_identity": _identity(fixture["bag"]),
            "noetic_prefix": str(fixture["prefix"].resolve()),
            "python_root_relative": module.DEFAULT_PYTHON_ROOT_RELATIVE,
            "rosbag_module_identity": _identity(fixture["rosbag"]),
            "rosbag_decoder_closure": {
                "rosbag": _identity(fixture["rosbag"]),
                "rosbag.bag": _identity(fixture["rosbag_bag"]),
            },
            "indexer_module_identity": _identity(fixture["indexer"]),
            "formal_manifest_identity": _identity(fixture["manifest"]),
            "probe_source_identity": _identity(fixture["probe_path"]),
            "sys_executable_identity": _identity(Path(sys.executable)),
            "parent_executable_admission": result[
                "parent_executable_admission"
            ],
            "capture_id": "capture-1",
            "scene": "background",
            "test_only": True,
            "trusted_system_python_roots": [],
            "output_path": str(fixture["output"].resolve()),
            "max_messages": module.DEFAULT_MAX_MESSAGES,
            "max_total_payload_bytes": module.DEFAULT_MAX_TOTAL_PAYLOAD_BYTES,
        }

    def _revalidate_output(self, fixture, result, marker=None):
        module = fixture["probe"]
        request = self._request_for_result(fixture, result)
        marker = copy.deepcopy(result["child_marker"] if marker is None else marker)
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(marker, sort_keys=True) + "\n", stderr="")
        return module._validate_child_result(
            completed,
            {"sha256": marker["request_sha256"]},
            request,
            request["bag_identity"],
            request["rosbag_module_identity"],
            request["indexer_module_identity"],
            request["formal_manifest_identity"],
            request["probe_source_identity"],
            request["sys_executable_identity"],
            fixture["output"],
        )

    def test_fresh_child_writes_bound_formal_artifact_and_restores_bytes(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            result = self._run(fixture)
            self.assertTrue(result["algorithm_validated"], result["failures"])
            self.assertFalse(result["validated_pass"])
            self.assertFalse(result["formal_acceptance"])
            self.assertTrue(result["not_in_four_scene_denominator"])
            self.assertEqual(
                [str(Path(sys.executable).resolve()), "-I", "-S", "-B"],
                result["argv"][:4])
            self.assertEqual(
                _identity(Path(sys.executable)),
                result["parent_executable_admission"]["target_identity"])
            self.assertEqual(
                _identity(Path(sys.executable)),
                result["child_executable_admission"]["target_identity"])
            self.assertFalse(result["delivery_ready"])
            connections, messages, formal = fixture["probe"].reconstruct_probe_records(
                fixture["output"])
            self.assertEqual(1, len(connections))
            self.assertEqual(b"\x00\x01\x02\xff", messages[0][
                "serialized_payload"])
            self.assertEqual(
                "formal_rgbd_raw_capture_index", formal["report_kind"])

    def test_identical_bound_material_replays_identical_output_identity(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            first = self._run(fixture)
            first_bytes = fixture["output"].read_bytes()
            self.assertTrue(first["algorithm_validated"], first["failures"])
            fixture["output"].unlink()

            second = self._run(fixture)
            self.assertTrue(second["algorithm_validated"], second["failures"])
            self.assertEqual(
                first["child_marker"]["request_id"],
                second["child_marker"]["request_id"],
            )
            self.assertEqual(
                first["request_identity"]["sha256"],
                second["request_identity"]["sha256"],
            )
            self.assertEqual(first["output_identity"], second["output_identity"])
            self.assertEqual(first_bytes, fixture["output"].read_bytes())

    def test_request_and_output_identity_bind_all_material_and_run_dimensions(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            baseline = self._run(fixture)
            self.assertTrue(
                baseline["algorithm_validated"], baseline["failures"])
            baseline_request_id = baseline["child_marker"]["request_id"]
            baseline_output_identity = baseline["output_identity"]
            request = self._request_for_result(fixture, baseline)
            self.assertEqual(
                baseline_request_id, module._deterministic_request_id(request))

            anchor_paths = (
                ("bag_identity",),
                ("rosbag_module_identity",),
                ("rosbag_decoder_closure", "rosbag"),
                ("rosbag_decoder_closure", "rosbag.bag"),
                ("indexer_module_identity",),
                ("formal_manifest_identity",),
                ("probe_source_identity",),
                ("sys_executable_identity",),
            )
            for path in anchor_paths:
                with self.subTest(anchor=".".join(path)):
                    changed = copy.deepcopy(request)
                    identity = changed
                    for key in path:
                        identity = identity[key]
                    identity["sha256"] = "0" * 64
                    self.assertNotEqual(
                        baseline_request_id,
                        module._deterministic_request_id(changed),
                    )

            malformed = copy.deepcopy(request)
            malformed["request_id"] = "0" * 64
            with self.assertRaises(module.ProbeError) as raised:
                module._validate_request(malformed)
            self.assertEqual(
                "probe_request_id_mismatch", raised.exception.code)

            fixture["output"].unlink()
            capture_changed = self._run(fixture, capture_id="capture-2")
            self.assertTrue(
                capture_changed["algorithm_validated"],
                capture_changed["failures"],
            )
            self.assertNotEqual(
                baseline_request_id,
                capture_changed["child_marker"]["request_id"],
            )
            self.assertNotEqual(
                baseline_output_identity, capture_changed["output_identity"])

            fixture["output"].unlink()
            scene_changed = self._run(fixture, scene="bin_only")
            self.assertTrue(
                scene_changed["algorithm_validated"], scene_changed["failures"])
            self.assertNotEqual(
                baseline_request_id,
                scene_changed["child_marker"]["request_id"],
            )
            self.assertNotEqual(
                baseline_output_identity, scene_changed["output_identity"])

            fixture["output"].unlink()
            other_output = Path(directory) / "probe-output-other.json"
            output_changed = self._run(fixture, output_path=other_output)
            self.assertTrue(
                output_changed["algorithm_validated"],
                output_changed["failures"],
            )
            self.assertNotEqual(
                baseline_request_id,
                output_changed["child_marker"]["request_id"],
            )
            self.assertNotEqual(
                baseline_output_identity, output_changed["output_identity"])

            fixture["manifest"].write_text(
                json.dumps({"manifest_id": "test-formal-v2"}),
                encoding="utf-8",
            )
            anchor_changed = self._run(fixture)
            self.assertTrue(
                anchor_changed["algorithm_validated"],
                anchor_changed["failures"],
            )
            self.assertNotEqual(
                baseline_request_id,
                anchor_changed["child_marker"]["request_id"],
            )
            self.assertNotEqual(
                baseline_output_identity, anchor_changed["output_identity"])

    def test_self_consistent_fake_prefix_never_receives_formal_acceptance(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            result = module.run_isolated_rosbag_probe(
                fixture["bag"], _identity(fixture["bag"]),
                fixture["prefix"], _identity(fixture["rosbag"]),
                {
                    "rosbag": _identity(fixture["rosbag"]),
                    "rosbag.bag": _identity(fixture["rosbag_bag"]),
                },
                _identity(fixture["indexer"]), fixture["manifest"],
                _identity(fixture["manifest"]),
                _identity(fixture["probe_path"]),
                _identity(Path(sys.executable)), "capture-1", "background",
                fixture["output"], admission_mode="production",
                timeout_sec=30.0)
            self.assertTrue(result["validated_pass"], result["failures"])
            self.assertTrue(result["algorithm_validated"])
            self.assertFalse(result["formal_acceptance"])
            self.assertTrue(result["not_in_four_scene_denominator"])
            self.assertFalse(result["delivery_ready"])

    def test_parent_fake_import_state_and_source_shadow_do_not_reach_child(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            shadow = Path(directory) / "devel" / "rosbag"
            shadow.mkdir(parents=True)
            (shadow / "__init__.py").write_text(
                "raise RuntimeError('shadow executed')\n", encoding="utf-8")
            fake = types.ModuleType("rosbag")
            finder = _AmbientFakeFinder()
            previous_module = sys.modules.get("rosbag")
            previous_path = list(sys.path)
            previous_meta = list(sys.meta_path)
            previous_environment = dict(os.environ)
            sys.modules["rosbag"] = fake
            sys.meta_path.insert(0, finder)
            os.environ["PYTHONPATH"] = str(shadow.parent)
            os.environ["ROS_MASTER_URI"] = "http://invalid:11311"
            os.environ["CMAKE_PREFIX_PATH"] = str(shadow.parent)
            try:
                result = self._run(fixture)
                self.assertTrue(
                    result["algorithm_validated"], result["failures"])
                self.assertFalse(result["validated_pass"])
                self.assertEqual(0, finder.calls)
                self.assertIs(sys.modules["rosbag"], fake)
                self.assertEqual(previous_path, sys.path)
                self.assertEqual(previous_meta[0], sys.meta_path[1])
                self.assertEqual("http://invalid:11311", os.environ[
                    "ROS_MASTER_URI"])
                self.assertTrue(result["parent_environment_restored"])
            finally:
                os.environ.clear()
                os.environ.update(previous_environment)
                sys.path[:] = previous_path
                sys.meta_path[:] = previous_meta
                if previous_module is None:
                    sys.modules.pop("rosbag", None)
                else:
                    sys.modules["rosbag"] = previous_module

    def test_wrong_rosbag_identity_is_rejected_before_child(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            wrong = dict(_identity(fixture["rosbag"]))
            wrong["sha256"] = "0" * 64
            result = fixture["probe"].run_isolated_rosbag_probe(
                fixture["bag"], _identity(fixture["bag"]),
                fixture["prefix"], wrong,
                {
                    "rosbag": _identity(fixture["rosbag"]),
                    "rosbag.bag": _identity(fixture["rosbag_bag"]),
                },
                _identity(fixture["indexer"]),
                fixture["manifest"], _identity(fixture["manifest"]),
                _identity(fixture["probe_path"]),
                _identity(Path(sys.executable)),
                "capture-1", "background", fixture["output"],
                admission_mode="test_only")
            self.assertFalse(result["validated_pass"])
            self.assertIn("rosbag_module_identity_mismatch", result["failures"])

    def test_zero_or_multiple_child_markers_are_rejected(self):
        for value in ("", "{}\n{}\n"):
            with self.subTest(value=value):
                with self.assertRaises(probe.ProbeError) as context:
                    probe._parse_single_child_marker(value)
                self.assertEqual(
                    "probe_child_marker_count_invalid", context.exception.code)

    def test_marker_strict_json_rejects_duplicate_nan_and_wrong_schema(self):
        cases = {
            "duplicate": '{"marker":"x","marker":"x"}\n',
            "nan": '{"value":NaN}\n',
            "wrong_schema": '{}\n',
        }
        for name, value in cases.items():
            with self.subTest(name=name), self.assertRaises(probe.ProbeError):
                probe._parse_single_child_marker(value)

    def test_nonzero_stderr_and_missing_marker_fail_closed(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            completed = subprocess.CompletedProcess(
                args=[], returncode=17, stdout="", stderr="bounded failure")
            with patch.object(module.subprocess, "run", return_value=completed):
                result = self._run(fixture)
            self.assertFalse(result["algorithm_validated"])
            self.assertIn("probe_child_exit_nonzero", result["failures"])
            self.assertIn("probe_child_stderr_not_empty", result["failures"])
            self.assertIn("probe_child_marker_count_invalid", result["failures"])

    def test_external_probe_and_executable_target_anchors_are_required(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            wrong_probe = dict(_identity(fixture["probe_path"]))
            wrong_probe["sha256"] = "0" * 64
            result = module.run_isolated_rosbag_probe(
                fixture["bag"], _identity(fixture["bag"]),
                fixture["prefix"], _identity(fixture["rosbag"]),
                {
                    "rosbag": _identity(fixture["rosbag"]),
                    "rosbag.bag": _identity(fixture["rosbag_bag"]),
                },
                _identity(fixture["indexer"]), fixture["manifest"],
                _identity(fixture["manifest"]), wrong_probe,
                _identity(Path(sys.executable)), "capture-1", "background",
                fixture["output"], admission_mode="test_only")
            self.assertIn("probe_source_identity_mismatch", result["failures"])

            wrong_executable = dict(_identity(Path(sys.executable)))
            wrong_executable["sha256"] = "0" * 64
            result = module.run_isolated_rosbag_probe(
                fixture["bag"], _identity(fixture["bag"]),
                fixture["prefix"], _identity(fixture["rosbag"]),
                {
                    "rosbag": _identity(fixture["rosbag"]),
                    "rosbag.bag": _identity(fixture["rosbag_bag"]),
                },
                _identity(fixture["indexer"]), fixture["manifest"],
                _identity(fixture["manifest"]),
                _identity(fixture["probe_path"]), wrong_executable,
                "capture-1", "background", fixture["output"],
                admission_mode="test_only")
            self.assertIn(
                "probe_executable_target_identity_mismatch",
                result["failures"])

    def test_decoder_closure_detects_bag_py_drift_before_child(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            stale_closure = {
                "rosbag": _identity(fixture["rosbag"]),
                "rosbag.bag": _identity(fixture["rosbag_bag"]),
            }
            fixture["rosbag_bag"].write_text(
                fixture["rosbag_bag"].read_text(encoding="utf-8")
                + "\nDRIFT = True\n", encoding="utf-8")
            result = module.run_isolated_rosbag_probe(
                fixture["bag"], _identity(fixture["bag"]),
                fixture["prefix"], _identity(fixture["rosbag"]),
                stale_closure, _identity(fixture["indexer"]),
                fixture["manifest"], _identity(fixture["manifest"]),
                _identity(fixture["probe_path"]),
                _identity(Path(sys.executable)), "capture-1", "background",
                fixture["output"], admission_mode="test_only")
            self.assertIn(
                "rosbag_decoder_closure_identity_mismatch",
                result["failures"])

    def test_missing_linklike_and_hardlinked_files_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.py"
            with self.assertRaises(probe.ProbeError) as missing_error:
                probe._regular_file_identity(missing)
            self.assertEqual("artifact_missing", missing_error.exception.code)

            regular = root / "regular.py"
            regular.write_text("x = 1\n", encoding="utf-8")
            with patch.object(
                    probe, "_path_has_linklike_component", return_value=True):
                with self.assertRaises(probe.ProbeError) as link_error:
                    probe._regular_file_identity(regular)
            self.assertEqual("artifact_path_linklike", link_error.exception.code)

            hardlink = root / "hardlink.py"
            os.link(regular, hardlink)
            with self.assertRaises(probe.ProbeError) as hardlink_error:
                probe._regular_file_identity(regular)
            self.assertEqual(
                "artifact_hardlink_forbidden", hardlink_error.exception.code)

    def test_marker_prefix_and_python_root_mismatch_are_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            result = self._run(fixture)
            marker = copy.deepcopy(result["child_marker"])
            marker["noetic_prefix"] = str(Path(directory) / "foreign")
            marker["python_root"] = str(Path(directory) / "foreign-python")
            validation = self._revalidate_output(fixture, result, marker)
            self.assertIn(
                "probe_child_marker_policy_invalid", validation["failures"])

    def test_payload_size_sha_and_total_are_recomputed(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            result = self._run(fixture)
            artifact = json.loads(fixture["output"].read_text(encoding="utf-8"))
            artifact["messages"][0]["serialized_payload_base64"] = base64.b64encode(
                b"tampered").decode("ascii")
            fixture["output"].write_text(
                json.dumps(artifact, sort_keys=True), encoding="utf-8")
            with self.assertRaises(probe.ProbeError) as context:
                probe.reconstruct_probe_records(fixture["output"])
            self.assertEqual(
                "probe_output_message_identity_mismatch", context.exception.code)
            self.assertFalse(result["formal_acceptance"])

    def test_duplicate_connection_and_message_records_fail_semantic_recompute(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            result = self._run(fixture)
            request = self._request_for_result(fixture, result)
            artifact = json.loads(fixture["output"].read_text(encoding="utf-8"))
            artifact["connections"].append(copy.deepcopy(artifact["connections"][0]))
            artifact["connection_count"] = len(artifact["connections"])
            with self.assertRaises(probe.ProbeError) as connection_error:
                probe._validate_artifact_semantics(artifact, request)
            self.assertEqual(
                "probe_output_connection_invalid", connection_error.exception.code)

            artifact = json.loads(fixture["output"].read_text(encoding="utf-8"))
            artifact["messages"].append(copy.deepcopy(artifact["messages"][0]))
            artifact["message_count"] = len(artifact["messages"])
            artifact["total_payload_bytes"] *= 2
            with self.assertRaises(probe.ProbeError) as message_error:
                probe._validate_artifact_semantics(artifact, request)
            self.assertEqual(
                "probe_output_duplicate_message", message_error.exception.code)

    def test_trusted_relative_entry_symlink_and_direct_target_share_anchor(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = _write_executable(root / "python3.14")
            entry = root / "python3"
            self._symlink_or_skip(entry, target.name)
            expected = _identity(target)

            linked = probe._admit_executable_entry(entry, expected)
            direct = probe._admit_executable_entry(target, expected)

            self.assertEqual(expected, linked["target_identity"])
            self.assertEqual(expected, direct["target_identity"])
            self.assertEqual(
                ["symlink", "regular_target"],
                [item["kind"] for item in linked["chain"]])
            self.assertEqual(target.name, linked["chain"][0]["link_target"])
            self.assertEqual(
                ["regular_target"],
                [item["kind"] for item in direct["chain"]])

    def test_executable_wrong_broken_loop_and_relative_escape_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = _write_executable(root / "python3.14", b"target\n")
            wrong = _write_executable(root / "python-wrong", b"wrong\n")
            expected = _identity(target)

            wrong_entry = root / "wrong-entry"
            self._symlink_or_skip(wrong_entry, wrong.name)
            broken_entry = root / "broken-entry"
            self._symlink_or_skip(broken_entry, "missing-target")
            loop_a = root / "loop-a"
            loop_b = root / "loop-b"
            self._symlink_or_skip(loop_a, loop_b.name)
            self._symlink_or_skip(loop_b, loop_a.name)
            nested = root / "bin"
            nested.mkdir()
            escaping = nested / "python3"
            self._symlink_or_skip(escaping, Path("..") / target.name)

            cases = (
                (wrong_entry, "probe_executable_target_identity_mismatch"),
                (broken_entry, "probe_executable_entry_broken_link"),
                (loop_a, "probe_executable_entry_loop"),
                (escaping, "probe_executable_entry_relative_escape"),
            )
            for candidate, code in cases:
                with self.subTest(code=code), self.assertRaises(
                        probe.ProbeError) as raised:
                    probe._admit_executable_entry(candidate, expected)
                self.assertEqual(code, raised.exception.code)

    def test_executable_chain_replacement_and_target_hash_drift_are_visible(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = _write_executable(root / "python3.14", b"target-v1\n")
            alias = root / "python-alias"
            entry = root / "python3"
            self._symlink_or_skip(entry, target.name)
            expected = _identity(target)
            before = probe._admit_executable_entry(entry, expected)

            entry.unlink()
            self._symlink_or_skip(alias, target.name)
            self._symlink_or_skip(entry, alias.name)
            after = probe._admit_executable_entry(entry, expected)
            self.assertNotEqual(before, after)
            self.assertEqual(expected, after["target_identity"])

            target.write_bytes(b"target-v2\n")
            target.chmod(target.stat().st_mode | 0o111)
            with self.assertRaises(probe.ProbeError) as raised:
                probe._admit_executable_entry(entry, expected)
            self.assertEqual(
                "probe_executable_target_identity_mismatch",
                raised.exception.code)

    def test_parent_detects_executable_chain_toctou_on_child_start(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            module = fixture["probe"]
            root = Path(directory)
            real_target = Path(sys.executable).resolve(strict=True)
            entry = root / "python3-entry"
            self._symlink_or_skip(entry, real_target)
            wrong = _write_executable(root / "python-wrong", b"wrong\n")
            real_run = module.subprocess.run

            def replace_chain_then_run(*args, **kwargs):
                entry.unlink()
                entry.symlink_to(wrong)
                return real_run(*args, **kwargs)

            with patch.object(module.sys, "executable", str(entry)), patch.object(
                    module.subprocess, "run", side_effect=replace_chain_then_run):
                result = self._run(fixture)
            self.assertFalse(result["algorithm_validated"])
            self.assertTrue(any(
                code in result["failures"] for code in (
                    "probe_parent_executable_chain_drift",
                    "probe_executable_target_identity_mismatch")), result)

    def test_child_executable_admission_marker_forgery_is_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            result = self._run(fixture)
            marker = copy.deepcopy(result["child_marker"])
            marker["child_executable_admission"]["target_identity"][
                "sha256"] = "0" * 64
            validation = self._revalidate_output(fixture, result, marker)
            self.assertIn(
                "probe_child_marker_policy_invalid", validation["failures"])


if __name__ == "__main__":
    unittest.main()
