"""Fresh-process exact integration for the ROS1 field-readiness CLI.

This test deliberately uses the real overlay ``rosbag1_isolated_probe.py``
and its real sibling indexer.  The only stand-in is a temporary, read-only
Noetic ``rosbag`` Python package which exposes deterministic rosbag API
records; no ROS graph, middleware, camera, model backend, or hardware is
started.  The complete four-scene fixture is explicitly test-only: each raw
bag is first decoded by the real isolated child, its semantic material is
then emitted by the anchored host producer, the probe artifact is removed,
and the field CLI must reproduce the exact probe identity before accepting
the material as algorithm-only evidence.  A separate minimal production
fixture proves that the unbound source-owned producer index blocks before a
request, probe output, or semantic output can be consumed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


WORKSPACE = Path(__file__).resolve().parents[3]
HOST_SOURCE = WORKSPACE / "src" / "limo_cleanup_perception"
OVERLAY = WORKSPACE / "ros1_overlay_src" / "limo_cleanup_ros1_perception"
OVERLAY_SOURCE = OVERLAY / "src"
PROBE_SOURCE = (
    OVERLAY_SOURCE
    / "limo_cleanup_ros1_perception"
    / "rosbag1_isolated_probe.py"
)
INDEXER_SOURCE = PROBE_SOURCE.with_name("rosbag1_rgbd_indexer.py")
FORMAL_MANIFEST = (
    OVERLAY
    / "config"
    / "dabai_ros1_formal_four_scene_six_topics_v1.json"
)

_IMPORT_PATH_BEFORE = list(sys.path)
try:
    for source_root in (HOST_SOURCE, OVERLAY_SOURCE, WORKSPACE):
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
    from limo_cleanup_perception import (  # noqa: E402
        ros1_noetic_field_readiness as GATE)
    from limo_cleanup_perception import (  # noqa: E402
        ros1_semantic_evidence_producer as PRODUCER)
finally:
    sys.path[:] = _IMPORT_PATH_BEFORE


FORMAL_BUILDERS = None


def _load_full_fixture_dependencies():
    """Load NumPy-dependent fixture builders only for the full integration."""
    global FORMAL_BUILDERS
    if FORMAL_BUILDERS is None:
        from src.limo_cleanup_perception.test import (
            test_ros1_formal_rosbag1_admission as formal_builders,
        )
        FORMAL_BUILDERS = formal_builders


PYTHON_ROOT_RELATIVE = "lib/python3/dist-packages"
SCENE_OFFSET_NS = 10_000_000_000
MODEL_HASHES = {
    "plastic_bottle": hashlib.sha256(b"plastic-bottle-model").hexdigest(),
    "trash_bin": hashlib.sha256(b"trash-bin-model").hexdigest(),
}
MODEL_SET_SHA256 = hashlib.sha256(
    json.dumps(
        [
            {"class_name": name, "sha256": MODEL_HASHES[name]}
            for name in ("plastic_bottle", "trash_bin")
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


def _json_bytes(value):
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


def _write_json(path, value):
    Path(path).write_bytes(_json_bytes(value))


def _write_jsonl(path, values):
    Path(path).write_bytes(b"".join(_json_bytes(value) for value in values))


def _identity(path):
    return dict(GATE.regular_file_identity(Path(path)))


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shift_decoded(decoded, offset_ns):
    value = copy.deepcopy(decoded)
    if isinstance(value, dict):
        header = value.get("header")
        if isinstance(header, dict) and header.get("stamp_ns", 0) > 0:
            header["stamp_ns"] += offset_ns
        transforms = value.get("transforms")
        if isinstance(transforms, list):
            for transform in transforms:
                child_header = transform.get("header")
                if (
                    isinstance(child_header, dict)
                    and child_header.get("stamp_ns", 0) > 0
                ):
                    child_header["stamp_ns"] += offset_ns
    return value


FAKE_ROSBAG_SOURCE = r'''
import json
from types import SimpleNamespace


class _Stamp:
    def __init__(self, value):
        self.value = int(value)

    def to_nsec(self):
        return self.value


class _SizedData:
    def __init__(self, size):
        self.size = int(size)

    def __len__(self):
        return self.size


def _header(value):
    return SimpleNamespace(
        stamp=_Stamp(value["stamp_ns"]), frame_id=value["frame_id"])


class _BaseMessage:
    def deserialize(self, raw):
        self._raw = bytes(raw)
        self._apply(json.loads(self._raw.decode("utf-8")))
        return self

    def serialize(self, stream):
        stream.write(self._raw)


class _Image(_BaseMessage):
    def _apply(self, value):
        self.header = _header(value["header"])
        self.height = value["height"]
        self.width = value["width"]
        self.encoding = value["encoding"]
        self.is_bigendian = value["is_bigendian"]
        self.step = value["step"]
        self.data = _SizedData(value["data_length"])


class _CameraInfo(_BaseMessage):
    def _apply(self, value):
        self.header = _header(value["header"])
        self.height = value["height"]
        self.width = value["width"]
        self.distortion_model = value["distortion_model"]
        self.D = value["D"]
        self.K = value["K"]
        self.R = value["R"]
        self.P = value["P"]
        self.binning_x = value["binning_x"]
        self.binning_y = value["binning_y"]
        self.roi = SimpleNamespace(**value["roi"])


class _TFMessage(_BaseMessage):
    def _apply(self, value):
        self.transforms = []
        for item in value["transforms"]:
            translation = item["translation_m"]
            rotation = item["rotation_xyzw"]
            self.transforms.append(SimpleNamespace(
                header=_header(item["header"]),
                child_frame_id=item["child_frame_id"],
                transform=SimpleNamespace(
                    translation=SimpleNamespace(
                        x=translation[0], y=translation[1], z=translation[2]),
                    rotation=SimpleNamespace(
                        x=rotation[0], y=rotation[1],
                        z=rotation[2], w=rotation[3]))))


_TYPES = {
    "sensor_msgs/Image": _Image,
    "sensor_msgs/CameraInfo": _CameraInfo,
    "tf2_msgs/TFMessage": _TFMessage,
}


class _Connection:
    def __init__(self, value):
        self.id = value["id"]
        self.topic = value["topic"]
        self.datatype = value["datatype"]
        self.md5sum = value["md5sum"]
        self.header = value["header"]


class Bag:
    version = 200

    def __init__(self, path, mode="r", allow_unindexed=False):
        if mode != "r" or allow_unindexed is not False:
            raise ValueError("read-only exact fixture expected")
        raw = open(path, "rb").read()
        magic, payload = raw.split(b"\n", 1)
        if magic != b"#ROSBAG V2.0":
            raise ValueError("not rosbag1 v2")
        self.value = json.loads(payload.decode("utf-8"))

    def _get_connections(self):
        return [_Connection(value) for value in self.value["connections"]]

    def read_messages(self, raw=True, return_connection_header=True):
        if raw is not True or return_connection_header is not True:
            raise ValueError("raw connection-header mode required")
        for item in self.value["messages"]:
            payload = bytes.fromhex(item["payload_hex"])
            pytype = _TYPES[item["datatype"]]
            raw_message = (
                item["datatype"], payload, item["md5sum"], 0, pytype)
            yield (
                item["topic"], raw_message,
                _Stamp(item["record_timestamp_ns"]), item["header"])

    def close(self):
        return None
'''.lstrip()


class _ExactCliFixture:
    def __init__(self, root):
        _load_full_fixture_dependencies()
        self.root = Path(root)
        self.prefix = self.root / "noetic"
        self.python_root = self.prefix.joinpath(*PYTHON_ROOT_RELATIVE.split("/"))
        self.rosbag_package = self.python_root / "rosbag"
        self.rosbag_package.mkdir(parents=True)
        self.rosbag_init = self.rosbag_package / "__init__.py"
        self.rosbag_impl = self.rosbag_package / "bag.py"
        self.rosbag_init.write_text("from .bag import Bag\n", encoding="utf-8")
        self.rosbag_impl.write_text(FAKE_ROSBAG_SOURCE, encoding="utf-8")

        self.install_path = self.root / "missing-real-install-evidence.json"
        _write_json(self.install_path, {
            "report_kind": "intentionally_invalid_install_evidence",
            "validated_pass": False,
        })
        self.install_identity = _identity(self.install_path)

        self.canonical_path = self.root / "canonical-source-admission.json"
        _write_json(self.canonical_path, {
            "report_kind": "test_only_canonical_source_placeholder",
            "validated_pass": False,
            "test_only": True,
        })
        self.canonical_identity = _identity(self.canonical_path)

        model_root = self.root / "models"
        model_root.mkdir()
        model_payloads = {
            "plastic_bottle": b"plastic-bottle-model",
            "trash_bin": b"trash-bin-model",
        }
        self.model_paths = {
            name: model_root / (name + ".engine")
            for name in GATE.MODEL_CLASSES
        }
        for name, path in self.model_paths.items():
            path.write_bytes(model_payloads[name])
        self.model_artifacts = {
            name: _identity(path) for name, path in self.model_paths.items()
        }
        self.asserted_model_hashes = {
            name: identity["sha256"]
            for name, identity in self.model_artifacts.items()
        }
        if self.asserted_model_hashes != MODEL_HASHES:
            raise AssertionError(self.asserted_model_hashes)
        self.model_manifest_path = self.root / "model-manifest.json"
        _write_json(self.model_manifest_path, {
            "schema_version": 1,
            "model_artifacts": self.model_artifacts,
            "model_set_sha256": MODEL_SET_SHA256,
        })
        self.model_manifest_identity = _identity(self.model_manifest_path)

        self.release_binding = {
            "release_id": "exact-cli-test-only-integration-v1",
            "source_manifest_artifact_sha256": _sha(
                "exact-cli-test-only-source-manifest"
            ),
            "source_set_sha256": _sha("exact-cli-test-only-source-set"),
            "manifest_generated_at_unix_sec": 1_700_000_000.0,
        }
        self.scenes = {}
        self.semantic_authorities = {}
        self.preflight_probe_identities = {}
        self.executable_target = _identity(
            Path(sys.executable).resolve(strict=True)
        )
        self.probe_module = GATE._load_exact_probe({
            "isolated_probe_source": _identity(PROBE_SOURCE),
            "rosbag1_indexer_source": _identity(INDEXER_SOURCE),
        })
        for scene_index, scene_name in enumerate(GATE.SCENES):
            self.scenes[scene_name] = self._build_scene(
                scene_name, scene_index
            )

        self.request_path = self.root / "field-readiness-request.json"
        self.authority_path = self.root / "field-readiness-authority.json"
        self.request = {
            "schema_version": 1,
            "marker": GATE.REQUEST_MARKER,
            "request_id": "exact-cli-test-only-request-v1",
            "mode": GATE.TEST_ONLY_MODE,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "runtime_family": "ROS1",
            "ros_distro": "noetic",
            "release_binding": self.release_binding,
            "model_artifact_sha256": dict(MODEL_HASHES),
            "model_set_sha256": MODEL_SET_SHA256,
            "canonical_source_admission": self.canonical_identity,
            "field_install_evidence": self.install_identity,
            "scenes": self.scenes,
        }
        self.refresh_authority()

    def _records_for_scene(self, scene_index):
        connections, messages = FORMAL_BUILDERS._records(
            FORMAL_BUILDERS.FRAME_COUNT
        )
        offset = scene_index * SCENE_OFFSET_NS
        shifted = []
        for message in messages:
            candidate = copy.deepcopy(message)
            candidate["record_timestamp_ns"] += offset
            candidate["decoded"] = _shift_decoded(
                candidate["decoded"], offset
            )
            candidate["serialized_payload"] = json.dumps(
                candidate["decoded"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            shifted.append(candidate)
        return connections, shifted

    def _write_bag(self, path, connections, messages):
        connection_by_id = {
            item["connection_id"]: item for item in connections
        }
        payload = {
            "connections": [
                {
                    "id": item["connection_id"],
                    "topic": item["topic"],
                    "datatype": item["type"],
                    "md5sum": item["md5sum"],
                    "header": item["connection_header"],
                }
                for item in connections
            ],
            "messages": [],
        }
        for message in messages:
            connection = connection_by_id[message["connection_id"]]
            payload["messages"].append({
                "topic": connection["topic"],
                "datatype": connection["type"],
                "md5sum": connection["md5sum"],
                "record_timestamp_ns": message["record_timestamp_ns"],
                "payload_hex": message["serialized_payload"].hex(),
                "header": message["connection_header"],
            })
        path.write_bytes(
            b"#ROSBAG V2.0\n"
            + json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )

    def _run_preflight_probe(self, scene_name, scene):
        result = self.probe_module.run_isolated_rosbag_probe(
            bag_path=Path(scene["artifacts"]["raw_bag"]["path"]),
            expected_bag_identity=scene["artifacts"]["raw_bag"],
            noetic_prefix=self.prefix,
            expected_rosbag_module_identity=_identity(self.rosbag_init),
            expected_rosbag_decoder_closure={
                "rosbag": _identity(self.rosbag_init),
                "rosbag.bag": _identity(self.rosbag_impl),
            },
            expected_indexer_module_identity=_identity(INDEXER_SOURCE),
            formal_manifest_path=FORMAL_MANIFEST,
            expected_formal_manifest_identity=_identity(FORMAL_MANIFEST),
            expected_probe_source_identity=_identity(PROBE_SOURCE),
            expected_sys_executable_identity=self.executable_target,
            capture_id=scene["capture_id"],
            scene=scene_name,
            output_path=Path(scene["probe_output_path"]),
            admission_mode="test_only",
            python_root_relative=PYTHON_ROOT_RELATIVE,
            trusted_system_python_roots=[],
        )
        if (
            result.get("algorithm_validated") is not True
            or result.get("validated_pass") is not False
            or result.get("formal_acceptance") is not False
            or result.get("not_in_four_scene_denominator") is not True
            or result.get("failures") != []
        ):
            raise AssertionError(result)
        return result

    def _produce_semantics(
        self, scene_name, scene, measurement_records, observation_ids
    ):
        group = Path(scene["artifacts"]["raw_bag"]["path"]).parent
        probe_identity = self.preflight_probe_identities[scene_name]
        review_path = group / "ground-truth-review-authority.json"
        measurement_path = group / "measurement-reference-authority.json"
        ledger_path = group / "semantic-measurement-ledger.json"
        producer_request_path = group / "semantic-producer-request.json"
        producer_authority_path = group / "semantic-producer-authority.json"
        output_root = group / "semantic-output-root"
        output_root.mkdir()
        output_directory = output_root / "material"

        truth_operator = "fixture-{}-truth-operator".format(scene_name)
        truth_reviewer = "fixture-{}-truth-reviewer".format(scene_name)
        extrinsics_operator = "fixture-{}-extrinsics-operator".format(
            scene_name
        )
        extrinsics_reviewer = "fixture-{}-extrinsics-reviewer".format(
            scene_name
        )
        measurement_method = "fixture-independent-measurement"
        _write_json(review_path, {
            "schema_version": 1,
            "marker": "LIMO_ROS1_GROUND_TRUTH_REVIEW_AUTHORITY_V1",
            "scope": "independent_ground_truth_review",
            "scene": scene_name,
            "capture_id": scene["capture_id"],
            "task_id": scene["task_id"],
            "raw_bag": scene["artifacts"]["raw_bag"],
            "typed_frames": scene["artifacts"]["typed_frames"],
            "operator_id": truth_operator,
            "reviewer_id": truth_reviewer,
            "reviewed_at_unix_sec": 1_700_000_000.0,
            "synthetic_test_only": True,
        })
        _write_json(measurement_path, {
            "schema_version": 1,
            "marker": "LIMO_ROS1_MEASUREMENT_REFERENCE_AUTHORITY_V1",
            "scope": "independent_extrinsics_xyz_depth_reference",
            "scene": scene_name,
            "capture_id": scene["capture_id"],
            "task_id": scene["task_id"],
            "raw_bag": scene["artifacts"]["raw_bag"],
            "probe_artifact": probe_identity,
            "typed_frames": scene["artifacts"]["typed_frames"],
            "extrinsics_operator_id": extrinsics_operator,
            "extrinsics_reviewer_id": extrinsics_reviewer,
            "measurement_method": measurement_method,
            "observation_ids": sorted(observation_ids),
            "authorized_at_unix_sec": 1_700_000_001.0,
            "synthetic_test_only": True,
        })
        review_identity = _identity(review_path)
        measurement_identity = _identity(measurement_path)
        ledger = {
            "schema_version": 1,
            "marker": PRODUCER.LEDGER_MARKER,
            "scene": scene_name,
            "capture_id": scene["capture_id"],
            "task_id": scene["task_id"],
            "raw_bag": scene["artifacts"]["raw_bag"],
            "probe_artifact": probe_identity,
            "typed_frames": scene["artifacts"]["typed_frames"],
            "typed_raw_binding": scene["artifacts"]["typed_raw_binding"],
            "canonical_source_admission": self.canonical_identity,
            "field_install_evidence": self.install_identity,
            "model_manifest": self.model_manifest_identity,
            "model_artifacts": self.model_artifacts,
            "model_set_sha256": MODEL_SET_SHA256,
            "ground_truth_review_authority": review_identity,
            "measurement_reference_authority": measurement_identity,
            "ground_truth_operator_id": truth_operator,
            "ground_truth_reviewer_id": truth_reviewer,
            "extrinsics": {
                "source_frame": "camera_color_optical_frame",
                "target_frame": "base_link",
                "translation_m": [0.0, 0.0, 0.0],
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "measurement_method": measurement_method,
                "operator_id": extrinsics_operator,
                "reviewer_id": extrinsics_reviewer,
                "measured_at_unix_sec": 1_699_999_000.0,
                "reviewed_at_unix_sec": 1_699_999_100.0,
            },
            "records": measurement_records,
        }
        _write_json(ledger_path, ledger)
        producer_request = {
            "schema_version": 1,
            "marker": PRODUCER.REQUEST_MARKER,
            "request_id": "exact-test-only-producer-request-{}".format(
                scene_name
            ),
            "mode": PRODUCER.TEST_ONLY_MODE,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "scene": scene_name,
            "capture_id": scene["capture_id"],
            "task_id": scene["task_id"],
            "raw_bag": scene["artifacts"]["raw_bag"],
            "probe_artifact": probe_identity,
            "typed_frames": scene["artifacts"]["typed_frames"],
            "typed_raw_binding": scene["artifacts"]["typed_raw_binding"],
            "measurement_ledger": _identity(ledger_path),
            "canonical_source_admission": self.canonical_identity,
            "field_install_evidence": self.install_identity,
            "model_manifest": self.model_manifest_identity,
            "model_artifacts": self.model_artifacts,
            "model_set_sha256": MODEL_SET_SHA256,
            "ground_truth_review_authority": review_identity,
            "measurement_reference_authority": measurement_identity,
            "output_directory": str(output_directory.resolve()),
        }
        _write_json(producer_request_path, producer_request)
        producer_authority = {
            "schema_version": 1,
            "marker": PRODUCER.AUTHORITY_MARKER,
            "authority_id": "exact-test-only-producer-authority-{}".format(
                scene_name
            ),
            "scope": "ros1_noetic_semantic_evidence_producer",
            "test_only": True,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "request_identity": _identity(producer_request_path),
            "producer_source": _identity(Path(PRODUCER.__file__)),
            "field_readiness_source": _identity(Path(GATE.__file__)),
            "canonical_source_admission": self.canonical_identity,
            "field_install_evidence": self.install_identity,
            "model_manifest": self.model_manifest_identity,
            "model_artifacts": self.model_artifacts,
            "model_set_sha256": MODEL_SET_SHA256,
            "ground_truth_review_authority": review_identity,
            "measurement_reference_authority": measurement_identity,
            "allowed_output_root": str(output_root.resolve()),
        }
        _write_json(producer_authority_path, producer_authority)
        producer_authority_identity = _identity(producer_authority_path)
        result = PRODUCER.produce_semantic_evidence(
            producer_request_path,
            producer_authority_path,
            producer_authority_identity,
            output_directory,
            test_only=True,
        )
        self.semantic_authorities[scene_name] = producer_authority_identity
        scene["artifacts"].update(result["outputs"])
        scene["artifacts"]["semantic_producer_report"] = result[
            "report_identity"
        ]
        return result

    def _targets(self, scene_name, frame_index):
        values = []
        if scene_name in ("bin_only", "bottle_in_bin", "bottle_outside"):
            values.append({
                "observation_id": "{}-{}-bin".format(
                    scene_name, frame_index
                ),
                "object_class": "trash_bin",
                "confidence": 0.99,
                "valid": True,
                "actionable": False,
                "status": "observed",
                "error_code": "",
                "position": {"x": 1.0, "y": 0.0, "z": 1.0},
                "size": {"x": 0.5, "y": 0.5, "z": 0.8},
                "bbox": [100.0, 100.0, 300.0, 300.0],
                "depth_m": 1.0,
                "depth_valid_pixels": 100,
                "depth_total_pixels": 100,
                "depth_valid_ratio": 1.0,
                "source": "exact_fixture_detector",
                "position_semantics": "base_link_from_independent_extrinsics",
            })
        if scene_name in ("bottle_in_bin", "bottle_outside"):
            values.append({
                "observation_id": "{}-{}-bottle".format(
                    scene_name, frame_index
                ),
                "object_class": "plastic_bottle",
                "confidence": 0.98,
                "valid": True,
                "actionable": scene_name == "bottle_outside",
                "status": (
                    "already_in_bin" if scene_name == "bottle_in_bin"
                    else "active"
                ),
                "error_code": "",
                "position": {"x": 0.5, "y": 0.0, "z": 1.0},
                "size": {"x": 0.1, "y": 0.1, "z": 0.25},
                "bbox": [20.0, 20.0, 80.0, 120.0],
                "depth_m": 1.0,
                "depth_valid_pixels": 100,
                "depth_total_pixels": 100,
                "depth_valid_ratio": 1.0,
                "source": "exact_fixture_detector",
                "position_semantics": "base_link_from_independent_extrinsics",
            })
        return values

    def _build_scene(self, scene_name, scene_index):
        group = self.root / "scenes" / scene_name
        group.mkdir(parents=True)
        capture_id = "exact-capture-{}-{}".format(scene_index, scene_name)
        task_id = "exact-task-{}-{}".format(scene_index, scene_name)
        connections, messages = self._records_for_scene(scene_index)
        bag_path = group / "capture.bag"
        self._write_bag(bag_path, connections, messages)
        bag_identity = _identity(bag_path)
        report = FORMAL_BUILDERS.INDEXER.inspect_records(
            connections,
            messages,
            capture_id,
            scene_name,
            FORMAL_BUILDERS.INDEXER.load_formal_manifest(FORMAL_MANIFEST),
            bag_identity,
            FORMAL_BUILDERS.INDEXER.FORMAL_CAMERA_ONLY_MODE,
        )
        if report.get("formal_acceptance") is not True:
            raise AssertionError(report.get("failures"))
        raw_tf = next(
            item for item in report["tf_graph"]["transforms"]
            if item["child_frame_id"] == "camera_color_optical_frame"
        )
        extrinsics_payload = {
            "source_frame": "camera_color_optical_frame",
            "target_frame": "base_link",
            "translation_m": [0.0, 0.0, 0.0],
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        }
        extrinsics_sha = GATE._canonical_sha256(extrinsics_payload)

        frames = []
        ground_records = []
        tf_records = []
        xyz_records = []
        depth_records = []
        latency_records = []
        measurement_records = []
        observation_ids = set()
        associations = []
        for row_index, bundle in enumerate(report["accepted_bundles"]):
            sequence = row_index + 1
            stamp_ns = bundle["header_stamps_ns"]["rgb"]
            bundle_id = _sha(
                "{}:{}:{}".format(scene_name, sequence, stamp_ns)
            )
            targets = self._targets(scene_name, row_index)
            frame = {
                "schema_version": 1,
                "read_only": True,
                "received_unix_sec": stamp_ns / 1e9 + 0.03,
                "transport_latency_sec": 0.03,
                "stamp": {
                    "sec": stamp_ns // 1_000_000_000,
                    "nanosec": stamp_ns % 1_000_000_000,
                },
                "frame_id": "camera_color_optical_frame",
                "task_id": task_id,
                "capture_id": capture_id,
                "bundle_id": bundle_id,
                "model_binding_sha256": MODEL_SET_SHA256,
                "sequence": sequence,
                "valid": True,
                "status": "targets_valid" if targets else "no_targets",
                "error_code": "",
                "sync_span_sec": 0.0,
                "processing_latency_sec": 0.01,
                "tf_target_frame": "base_link",
                "tf_valid": True,
                "tf_transform_applied": True,
                "tf_status": "applied",
                "tf_error_code": "",
                "targets": targets,
                "scene": scene_name,
            }
            frames.append(frame)
            associations.append({
                "typed_row_index": row_index,
                "sequence": sequence,
                "stamp_ns": stamp_ns,
                "bundle_id": bundle_id,
                "typed_frame_sha256": GATE._canonical_sha256(frame),
                "raw_bundle_index": bundle["index"],
                "raw_stream_payload_sha256": bundle[
                    "stream_payload_sha256"
                ],
            })

            annotations = []
            observations = []
            for target in targets:
                annotation = {
                    "instance_id": target["observation_id"],
                    "object_class": target["object_class"],
                    "bbox": target["bbox"],
                    "relation": (
                        "container"
                        if target["object_class"] == "trash_bin"
                        else (
                            "inside_bin"
                            if scene_name == "bottle_in_bin"
                            else "outside_bin"
                        )
                    ),
                }
                annotations.append(annotation)
                observation_ids.add(target["observation_id"])
                observations.append({
                    "observation_id": target["observation_id"],
                    "camera_xyz_m": [
                        target["position"]["x"],
                        target["position"]["y"],
                        target["position"]["z"],
                    ],
                    "reference_xyz_m": [
                        target["position"]["x"],
                        target["position"]["y"],
                        target["position"]["z"],
                    ],
                    "reference_depth_m": target["depth_m"],
                })
            ground_records.append({
                "sequence": sequence,
                "stamp_ns": stamp_ns,
                "bundle_id": bundle_id,
                "typed_frame_sha256": GATE._canonical_sha256(frame),
                "rgb_payload_sha256": bundle["stream_payload_sha256"]["rgb"],
                "annotations": annotations,
            })
            tf_records.append({
                "sequence": sequence,
                "stamp_ns": stamp_ns,
                "bundle_id": bundle_id,
                "topic": raw_tf["topic"],
                "message_id": raw_tf["message_id"],
                "connection_id": raw_tf["connection_id"],
                "transform_index": raw_tf["transform_index"],
                "callerid": raw_tf["callerid"],
                "transform_stamp_ns": raw_tf["stamp_ns"],
                "parent_frame_id": raw_tf["parent_frame_id"],
                "child_frame_id": raw_tf["child_frame_id"],
                "lookup_source_frame": "camera_color_optical_frame",
                "lookup_target_frame": "base_link",
                "translation_m": raw_tf["translation_m"],
                "rotation_xyzw": raw_tf["rotation_xyzw"],
                "serialized_sha256": raw_tf["serialized_sha256"],
                "lookup_succeeded": True,
                "transform_applied": True,
                "output_frame": "base_link",
                "extrinsics_transform_sha256": extrinsics_sha,
                "target_transforms": [
                    {
                        "observation_id": target["observation_id"],
                        "input_position_m": [
                            target["position"]["x"],
                            target["position"]["y"],
                            target["position"]["z"],
                        ],
                        "output_position_m": [
                            target["position"]["x"],
                            target["position"]["y"],
                            target["position"]["z"],
                        ],
                        "extrinsics_transform_sha256": extrinsics_sha,
                    }
                    for target in targets
                ],
            })
            for target in targets:
                common = {
                    "sequence": sequence,
                    "stamp_ns": stamp_ns,
                    "bundle_id": bundle_id,
                    "observation_id": target["observation_id"],
                }
                xyz_records.append({
                    **common,
                    "reference_xyz_m": [
                        target["position"]["x"],
                        target["position"]["y"],
                        target["position"]["z"],
                    ],
                    "measured_xyz_m": [
                        target["position"]["x"],
                        target["position"]["y"],
                        target["position"]["z"],
                    ],
                    "error_m": 0.0,
                })
                depth_records.append({
                    **common,
                    "reference_depth_m": target["depth_m"],
                    "measured_depth_m": target["depth_m"],
                    "valid_pixels": target["depth_valid_pixels"],
                    "total_pixels": target["depth_total_pixels"],
                    "valid_ratio": target["depth_valid_ratio"],
                    "valid": True,
                    "error_m": 0.0,
                })
            sensor = stamp_ns / 1e9
            started = sensor + 0.005
            ended = sensor + 0.015
            collected = sensor + 0.03
            measurement_records.append({
                "sequence": sequence,
                "stamp_ns": stamp_ns,
                "bundle_id": bundle_id,
                "typed_frame_sha256": GATE._canonical_sha256(frame),
                "rgb_payload_sha256": bundle[
                    "stream_payload_sha256"
                ]["rgb"],
                "annotations": annotations,
                "observations": observations,
                "inference_started_unix_sec": started,
                "inference_ended_unix_sec": ended,
            })
            latency_records.append({
                "sequence": sequence,
                "stamp_ns": stamp_ns,
                "bundle_id": bundle_id,
                "sensor_stamp_sec": sensor,
                "inference_started_unix_sec": started,
                "inference_ended_unix_sec": ended,
                "collector_received_unix_sec": collected,
                "sync_span_sec": 0.0,
                "processing_latency_sec": ended - started,
                "transport_latency_sec": collected - sensor,
                "end_to_end_latency_sec": collected - sensor,
            })

        frames_path = group / "typed_frames.jsonl"
        _write_jsonl(frames_path, frames)
        frames_identity = _identity(frames_path)
        collector_path = group / "collector.json"
        _write_json(collector_path, {
            "schema_version": 1,
            "collector_kind": GATE.ARTIFACT_MARKERS["collector_manifest"],
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "scene": scene_name,
            "topic": GATE.EXPECTED_COLLECTOR_TOPIC,
            "message_type": GATE.EXPECTED_COLLECTOR_MESSAGE_TYPE,
            "task_id": task_id,
            "max_frames": len(frames),
            "duration_sec": 2.0,
            "received_frames": len(frames),
            "unique_frames": len(frames),
            "duplicate_sequences": 0,
            "duplicate_bundle_ids": 0,
            "serialization_errors": 0,
            "interrupted": False,
            "completed_minimum": True,
            "completed_requested_frames": True,
            "output": frames_identity,
        })
        binding_path = group / "typed_raw_binding.json"
        _write_json(binding_path, {
            "schema_version": 2,
            "report_kind": GATE.ARTIFACT_MARKERS["typed_raw_binding"],
            "evidence_scope": "test_only_rosbag1_typed_raw_binding",
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "binding_sha256": _sha("binding:" + scene_name),
            "capture_id": capture_id,
            "task_id": task_id,
            "scene": scene_name,
            "model_binding_sha256": MODEL_SET_SHA256,
            "artifacts": {"raw_bag": bag_identity, "typed_frames": frames_identity},
            "provenance": {"formal_report_sha256": GATE._canonical_sha256(report)},
            "typed_frame_count": len(frames),
            "raw_bundle_count": len(report["accepted_bundles"]),
            "association_count": len(associations),
            "minimum_scene_frames": 1,
            "unpaired_typed_count": 0,
            "unpaired_raw_bundle_count": 0,
            "associations": associations,
            "test_only": True,
            "validated_pass": True,
            "formal_acceptance": False,
            "not_in_four_scene_denominator": True,
            "delivery_ready": False,
            "failures": [],
        })

        common = {
            "schema_version": 1,
            "scene": scene_name,
            "capture_id": capture_id,
            "task_id": task_id,
            "ros1_field_install_sha256": self.install_identity["sha256"],
            "model_binding_sha256": MODEL_SET_SHA256,
            "synthetic_test_only": True,
        }
        frame_map = {
            (frame["sequence"],
             frame["stamp"]["sec"] * 1_000_000_000
             + frame["stamp"]["nanosec"], frame["bundle_id"]):
            (index, frame)
            for index, frame in enumerate(frames)
        }
        ground_map = {
            (record["sequence"], record["stamp_ns"], record["bundle_id"]):
            record for record in ground_records
        }
        ground_path = group / "ground_truth.json"
        _write_json(ground_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["ground_truth"],
            "complete": True,
            "unique_frames": len(ground_records),
            "annotation_count": sum(
                len(record["annotations"]) for record in ground_records
            ),
            "class_metrics": GATE._class_metrics(ground_map, frame_map),
            "records": ground_records,
        })
        extrinsics_path = group / "extrinsics.json"
        _write_json(extrinsics_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["extrinsics_reference"],
            **extrinsics_payload,
            "transform_sha256": extrinsics_sha,
            "measurement_method": "independent_fixture_measurement",
            "operator_id": "exact-fixture-operator",
            "reviewer_id": "exact-fixture-reviewer",
            "measured_at_unix_sec": 1_699_999_000.0,
            "reviewed_at_unix_sec": 1_699_999_100.0,
        })
        tf_path = group / "tf.json"
        _write_json(tf_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["tf_records"],
            "source_frame": "camera_color_optical_frame",
            "target_frame": "base_link",
            "transform_applied": True,
            "mixed_tf": False,
            "tf_valid_frames": len(tf_records),
            "xyz_valid_frames": len(tf_records),
            "records": tf_records,
        })
        xyz_errors = [record["error_m"] for record in xyz_records]
        xyz_path = group / "xyz.json"
        _write_json(xyz_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["xyz_records"],
            "not_applicable": not bool(xyz_records),
            "sample_count": len(xyz_records),
            "max_error_m": max(xyz_errors) if xyz_errors else None,
            "p95_error_m": GATE._p95(xyz_errors),
            "records": xyz_records,
        })
        depth_errors = [record["error_m"] for record in depth_records]
        depth_path = group / "depth.json"
        _write_json(depth_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["depth_records"],
            "not_applicable": not bool(depth_records),
            "sample_count": len(depth_records),
            "valid_rate": 1.0 if depth_records else None,
            "max_error_m": max(depth_errors) if depth_errors else None,
            "p95_error_m": GATE._p95(depth_errors),
            "records": depth_records,
        })
        end_to_end = [
            record["end_to_end_latency_sec"] for record in latency_records
        ]
        processing = [
            record["processing_latency_sec"] for record in latency_records
        ]
        sync = [record["sync_span_sec"] for record in latency_records]
        latency_path = group / "latency.json"
        _write_json(latency_path, {
            **common,
            "report_kind": GATE.ARTIFACT_MARKERS["latency_records"],
            "sample_count": len(latency_records),
            "max_latency_sec": max(end_to_end),
            "p95_end_to_end_sec": GATE._p95(end_to_end),
            "p95_processing_sec": GATE._p95(processing),
            "p95_sync_sec": GATE._p95(sync),
            "records": latency_records,
        })

        scene = {
            "scene": scene_name,
            "capture_id": capture_id,
            "task_id": task_id,
            "bundle_id": _sha("scene-envelope:" + scene_name),
            "capture_window": report["capture_window"],
            "collector_request": {
                "topic": GATE.EXPECTED_COLLECTOR_TOPIC,
                "message_type": GATE.EXPECTED_COLLECTOR_MESSAGE_TYPE,
                "max_frames": len(frames),
                "duration_sec": 2.0,
            },
            "probe_output_path": str((group / "probe-output.json").resolve()),
            "artifacts": {
                "raw_bag": bag_identity,
                "collector_manifest": _identity(collector_path),
                "typed_frames": frames_identity,
                "typed_raw_binding": _identity(binding_path),
                "ground_truth": _identity(ground_path),
                "extrinsics_reference": _identity(extrinsics_path),
                "tf_records": _identity(tf_path),
                "xyz_records": _identity(xyz_path),
                "depth_records": _identity(depth_path),
                "latency_records": _identity(latency_path),
            },
        }
        preflight = self._run_preflight_probe(scene_name, scene)
        self.preflight_probe_identities[scene_name] = dict(
            preflight["output_identity"]
        )
        self._produce_semantics(
            scene_name, scene, measurement_records, observation_ids
        )
        Path(scene["probe_output_path"]).unlink()
        return scene

    def refresh_authority(self):
        _write_json(self.request_path, self.request)
        self.authority = {
            "schema_version": 1,
            "marker": GATE.AUTHORITY_MARKER,
            "authority_id": "exact-cli-test-only-authority-v1",
            "scope": "ros1_noetic_field_readiness_intake",
            "test_only": True,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "request_identity": _identity(self.request_path),
            "canonical_source_admission": self.canonical_identity,
            "field_install_evidence": self.install_identity,
            "formal_manifest": _identity(FORMAL_MANIFEST),
            "isolated_probe_source": _identity(PROBE_SOURCE),
            "rosbag1_indexer_source": _identity(INDEXER_SOURCE),
            "rosbag_module": _identity(self.rosbag_init),
            "noetic_prefix": str(self.prefix.resolve()),
            "rosbag_decoder_closure": {
                "rosbag": _identity(self.rosbag_init),
                "rosbag.bag": _identity(self.rosbag_impl),
            },
            "python_executable_target": self.executable_target,
            "trusted_system_python_roots": [],
            "python_root_relative": PYTHON_ROOT_RELATIVE,
            "scene_set": list(GATE.SCENES),
            "artifact_markers": dict(GATE.ARTIFACT_MARKERS),
            "semantic_producer_source": _identity(Path(PRODUCER.__file__)),
            "semantic_producer_authorities": dict(
                self.semantic_authorities
            ),
        }
        _write_json(self.authority_path, self.authority)
        self.authority_identity = _identity(self.authority_path)

    def commit_authority(self):
        _write_json(self.authority_path, self.authority)
        self.authority_identity = _identity(self.authority_path)

    def run_cli(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {
                "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "PATHEXT",
                "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR",
            }
        }
        environment["PYTHONPATH"] = str(HOST_SOURCE)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        argv = [
            sys.executable,
            "-B",
            "-m",
            "limo_cleanup_perception.ros1_noetic_field_readiness",
            "--request",
            str(self.request_path),
            "--authority",
            str(self.authority_path),
            "--authority-size-bytes",
            str(self.authority_identity["size_bytes"]),
            "--authority-sha256",
            self.authority_identity["sha256"],
            "--workspace",
            str(WORKSPACE),
        ]
        completed = subprocess.run(
            argv,
            cwd=str(WORKSPACE),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=180.0,
            check=False,
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.last_argv = argv
        self.last_completed = completed
        if len(lines) != 1:
            raise AssertionError({
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            })
        return json.loads(lines[0])


class _LinklikePrefixCliFixture:
    """Stdlib-only production CLI fixture for the POSIX symlink preflight."""

    def __init__(self, root):
        self.root = Path(root)
        self.prefix = self.root / "noetic"
        self.python_root = self.prefix.joinpath(*PYTHON_ROOT_RELATIVE.split("/"))
        self.python_root.mkdir(parents=True)
        self.rosbag_package = self.python_root / "rosbag"
        self.rosbag_package.mkdir()
        self.rosbag_init = self.rosbag_package / "__init__.py"
        self.rosbag_impl = self.rosbag_package / "bag.py"
        self.rosbag_init.write_text("from .bag import Bag\n", encoding="utf-8")
        self.rosbag_impl.write_text("class Bag: pass\n", encoding="utf-8")

        self.request_path = self.root / "request.json"
        _write_json(self.request_path, {})
        self.dummy_identity_paths = {}
        for name in (
            "canonical", "install", "formal", "probe", "indexer",
        ):
            path = self.root / (name + ".json")
            if name in {"probe", "indexer"}:
                path = self.root / (
                    "rosbag1_isolated_probe.py"
                    if name == "probe" else "rosbag1_rgbd_indexer.py"
                )
            path.write_text("{}\n", encoding="utf-8")
            self.dummy_identity_paths[name] = path
        self.semantic_authority_paths = {}
        for scene_name in GATE.SCENES:
            path = self.root / (
                "semantic-authority-{}.json".format(scene_name)
            )
            _write_json(path, {"scene": scene_name, "unselected": True})
            self.semantic_authority_paths[scene_name] = path
        self.scene_output_paths = []
        for scene_name in GATE.SCENES:
            self.scene_output_paths.extend((
                self.root / scene_name / "probe-output.json",
                self.root / scene_name / "semantic-output",
            ))

        self.authority_path = self.root / "authority.json"
        self.authority = {
            "schema_version": 1,
            "marker": GATE.AUTHORITY_MARKER,
            "authority_id": "exact-cli-linklike-prefix-posix-v1",
            "scope": "ros1_noetic_field_readiness_intake",
            "test_only": False,
            "read_only": True,
            "authorizes_motion": False,
            "publishes_ros_messages": False,
            "request_identity": _identity(self.request_path),
            "canonical_source_admission": _identity(
                self.dummy_identity_paths["canonical"]
            ),
            "field_install_evidence": _identity(
                self.dummy_identity_paths["install"]
            ),
            "formal_manifest": _identity(self.dummy_identity_paths["formal"]),
            "isolated_probe_source": _identity(
                self.dummy_identity_paths["probe"]
            ),
            "rosbag1_indexer_source": _identity(
                self.dummy_identity_paths["indexer"]
            ),
            "rosbag_module": _identity(self.rosbag_init),
            "noetic_prefix": str(self.prefix.resolve()),
            "rosbag_decoder_closure": {
                "rosbag": _identity(self.rosbag_init),
                "rosbag.bag": _identity(self.rosbag_impl),
            },
            "python_executable_target": _identity(
                Path(sys.executable).resolve(strict=True)
            ),
            "trusted_system_python_roots": [],
            "python_root_relative": PYTHON_ROOT_RELATIVE,
            "scene_set": list(GATE.SCENES),
            "artifact_markers": dict(GATE.ARTIFACT_MARKERS),
            "semantic_producer_source": _identity(Path(PRODUCER.__file__)),
            "semantic_producer_authorities": {
                scene_name: _identity(path)
                for scene_name, path in self.semantic_authority_paths.items()
            },
        }
        self.commit_authority()

    def commit_authority(self):
        _write_json(self.authority_path, self.authority)
        self.authority_identity = _identity(self.authority_path)

    def run_cli(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {
                "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "PATHEXT",
                "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR",
            }
        }
        environment["PYTHONPATH"] = str(HOST_SOURCE)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "limo_cleanup_perception.ros1_noetic_field_readiness",
                "--request",
                str(self.request_path),
                "--authority",
                str(self.authority_path),
                "--authority-size-bytes",
                str(self.authority_identity["size_bytes"]),
                "--authority-sha256",
                self.authority_identity["sha256"],
                "--workspace",
                str(WORKSPACE),
            ],
            cwd=str(WORKSPACE),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30.0,
            check=False,
        )
        self.last_completed = completed
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise AssertionError({
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            })
        return json.loads(lines[0])


class Ros1NoeticFieldReadinessExactCliTest(unittest.TestCase):
    def test_test_only_cli_repeats_real_probe_and_recomputes_producer_material(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            result = fixture.run_cli()
            self.assertEqual(1, fixture.last_completed.returncode)
            self.assertEqual("", fixture.last_completed.stderr)
            self.assertTrue(result["algorithm_validated"], result["failures"])
            self.assertTrue(result["validator_unit_test_pass"])
            self.assertEqual(GATE.TEST_ONLY_MODE, result["mode"])
            self.assertEqual(set(GATE.SCENES), set(result["scene_reports"]))
            for scene_name in GATE.SCENES:
                scene_report = result["scene_reports"][scene_name]
                self.assertTrue(scene_report["algorithm_validated"])
                self.assertEqual([], scene_report["failures"])
                self.assertEqual(
                    GATE.MIN_PRODUCTION_SCENE_FRAMES,
                    scene_report["semantic_recompute"]["typed_frame_count"],
                )
                probe_output = Path(
                    fixture.scenes[scene_name]["probe_output_path"]
                )
                self.assertTrue(probe_output.is_file())
                artifact = json.loads(probe_output.read_text(encoding="utf-8"))
                self.assertTrue(artifact["algorithm_validated"])
                self.assertTrue(artifact["test_only"])
                self.assertFalse(artifact["formal_acceptance"])
                self.assertTrue(artifact["not_in_four_scene_denominator"])
                self.assertEqual(
                    fixture.preflight_probe_identities[scene_name],
                    scene_report["probe_output_identity"],
                )
                self.assertEqual(
                    GATE.MIN_PRODUCTION_SCENE_FRAMES,
                    len(artifact["formal_report"]["accepted_bundles"]),
                )
                producer_report = scene_report["semantic_producer"]
                self.assertTrue(producer_report["synthetic_test_only"])
                self.assertEqual(
                    fixture.semantic_authorities[scene_name],
                    producer_report["authority_identity"],
                )
                self.assertEqual(
                    fixture.scenes[scene_name]["artifacts"][
                        "semantic_producer_report"
                    ],
                    producer_report["report_identity"],
                )
            self.assertIsNone(result["canonical_probe_binding"])
            self.assertFalse(result["source_gate_pass"])
            self.assertFalse(result["ros1_noetic_field_install_pass"])
            self.assertFalse(result["formal_four_scene_pass"])
            self.assertFalse(result["formal_tf_3d_pass"])
            self.assertFalse(result["field_evidence_admitted"])
            self.assertFalse(result["formal_acceptance"])
            self.assertFalse(result["delivery_ready"])
            self.assertFalse(result["accepted_by_formal_evidence_consumer"])
            self.assertEqual(
                ["synthetic_test_only_not_formal_evidence"],
                result["failures"],
            )

    def test_production_cli_blocks_on_unbound_producer_index_before_inputs(self):
        with TemporaryDirectory() as directory:
            fixture = _LinklikePrefixCliFixture(directory)
            result = fixture.run_cli()
            self.assertEqual(1, fixture.last_completed.returncode)
            self.assertFalse(result["algorithm_validated"])
            self.assertEqual(
                ["semantic_producer_production_authority_not_anchored"],
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])
            self.assertIsNone(result["runtime_authority_admission"])
            for path in fixture.scene_output_paths:
                self.assertFalse(path.exists())

    def test_production_probe_injection_is_rejected_before_runner(self):
        with TemporaryDirectory() as directory:
            fixture = _LinklikePrefixCliFixture(directory)
            calls = []

            def forbidden_runner(**kwargs):
                calls.append(kwargs)
                return {}

            result = GATE.evaluate_field_readiness(
                fixture.request_path,
                fixture.authority_path,
                fixture.authority_identity,
                workspace=WORKSPACE,
                probe_runner=forbidden_runner,
            )
            self.assertEqual([], calls)
            self.assertFalse(result["algorithm_validated"])
            self.assertEqual(
                ["production_probe_injection_forbidden"],
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])
            for path in fixture.scene_output_paths:
                self.assertFalse(path.exists())

    def test_decoder_closure_identity_drift_fails_before_probe(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            fixture.authority["rosbag_decoder_closure"]["rosbag.bag"] = {
                **fixture.authority["rosbag_decoder_closure"]["rosbag.bag"],
                "sha256": "0" * 64,
            }
            _write_json(fixture.authority_path, fixture.authority)
            fixture.authority_identity = _identity(fixture.authority_path)
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertTrue(any(
                "authority_rosbag_decoder_closure:rosbag.bag_identity_mismatch"
                in failure
                for failure in result["failures"]
            ), result["failures"])
            self.assertEqual({}, result["scene_reports"])

    def test_request_marker_drift_fails_before_any_scene_output(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            fixture.request["marker"] = "NOT_THE_HOST_REQUEST_MARKER"
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn("request_policy_invalid", result["failures"])
            self.assertEqual({}, result["scene_reports"])
            for scene in fixture.scenes.values():
                self.assertFalse(Path(scene["probe_output_path"]).exists())

    def test_missing_semantic_producer_report_fails_before_probe(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            report_path = Path(
                fixture.scenes["background"]["artifacts"][
                    "semantic_producer_report"
                ]["path"]
            )
            report_path.unlink()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertEqual(
                [
                    "artifact_missing",
                    "synthetic_test_only_not_formal_evidence",
                ],
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])
            for scene in fixture.scenes.values():
                self.assertFalse(Path(scene["probe_output_path"]).exists())

    def test_forged_semantic_producer_report_is_rejected_after_recompute(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            scene = fixture.scenes["background"]
            report_path = Path(
                scene["artifacts"]["semantic_producer_report"]["path"]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["producer_material_validated"] = False
            _write_json(report_path, report)
            scene["artifacts"]["semantic_producer_report"] = _identity(
                report_path
            )
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertEqual(
                [
                    "semantic_producer_report_policy_invalid:background",
                    "synthetic_test_only_not_formal_evidence",
                ],
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])

    def test_semantic_output_identity_drift_is_rejected_by_report_binding(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            scene = fixture.scenes["background"]
            output_path = Path(scene["artifacts"]["ground_truth"]["path"])
            output_path.write_bytes(output_path.read_bytes() + b" \n")
            scene["artifacts"]["ground_truth"] = _identity(output_path)
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertEqual(
                [
                    "semantic_producer_report_policy_invalid:background",
                    "synthetic_test_only_not_formal_evidence",
                ],
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])

    def test_wrong_executable_target_fails_before_child_execution(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            sentinel = fixture.root / "wrong-executable-ran.txt"
            replacement = fixture.root / "wrong-python-target.py"
            replacement.write_text(
                "from pathlib import Path\n"
                + "Path({!r}).write_text('executed')\n".format(str(sentinel)),
                encoding="utf-8",
            )
            if os.name != "nt":
                replacement.chmod(0o755)
            fixture.authority["python_executable_target"] = _identity(
                replacement
            )
            fixture.commit_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn(
                "isolated_probe_result_not_valid:background",
                result["failures"],
            )
            self.assertFalse(sentinel.exists())
            self.assertEqual({}, result["scene_reports"])

    def test_missing_noetic_root_is_rejected_before_probe_load(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            fixture.authority["noetic_prefix"] = str(
                (fixture.root / "missing-noetic-prefix").resolve()
            )
            fixture.commit_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn("authority_noetic_prefix_linklike", result["failures"])
            self.assertEqual({}, result["scene_reports"])

    def test_linklike_python_root_is_rejected_before_probe_load(self):
        with TemporaryDirectory() as directory:
            fixture = _LinklikePrefixCliFixture(directory)
            link_prefix = fixture.root / "linked-noetic"
            try:
                os.symlink(fixture.prefix, link_prefix, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("platform does not permit directory symlinks")
            fixture.authority["noetic_prefix"] = str(link_prefix.absolute())
            fixture.commit_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn("authority_noetic_prefix_linklike", result["failures"])
            self.assertEqual({}, result["scene_reports"])

    def test_child_stdout_marker_noise_is_rejected_by_real_probe(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            original = fixture.rosbag_impl.read_text(encoding="utf-8")
            fixture.rosbag_impl.write_text(
                "print('UNTRUSTED_CHILD_STDOUT')\n" + original,
                encoding="utf-8",
            )
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn(
                "isolated_probe_result_not_valid:background",
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])

    def test_duplicate_raw_record_is_rejected_by_real_redecode(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            scene = fixture.request["scenes"]["background"]
            bag_path = Path(scene["artifacts"]["raw_bag"]["path"])
            magic, encoded = bag_path.read_bytes().split(b"\n", 1)
            payload = json.loads(encoded.decode("utf-8"))
            payload["messages"].append(copy.deepcopy(payload["messages"][3]))
            bag_path.write_bytes(
                magic
                + b"\n"
                + json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
            scene["artifacts"]["raw_bag"] = _identity(bag_path)
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn(
                "isolated_probe_result_not_valid:background",
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])

    def test_formal_manifest_report_denominator_mismatch_fails_closed(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            manifest = json.loads(FORMAL_MANIFEST.read_text(encoding="utf-8"))
            manifest["min_accepted_bundles"] = (
                GATE.MIN_PRODUCTION_SCENE_FRAMES + 1
            )
            replacement = fixture.root / "formal-manifest-31.json"
            _write_json(replacement, manifest)
            fixture.authority["formal_manifest"] = _identity(replacement)
            fixture.commit_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn(
                "isolated_probe_result_not_valid:background",
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])

    def test_child_output_embedded_report_tamper_is_recomputed_and_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = _ExactCliFixture(directory)
            original = fixture.rosbag_impl.read_text(encoding="utf-8")
            tamper = r'''

import atexit as _atexit
from pathlib import Path as _Path

_original_bag_init = Bag.__init__
_tamper_output = None

def _capturing_bag_init(self, path, mode="r", allow_unindexed=False):
    global _tamper_output
    _tamper_output = _Path(path).parent / "probe-output.json"
    return _original_bag_init(self, path, mode, allow_unindexed)

Bag.__init__ = _capturing_bag_init

def _tamper_embedded_report():
    if _tamper_output is None or not _tamper_output.exists():
        return
    value = json.loads(_tamper_output.read_text(encoding="utf-8"))
    value["formal_report"]["accepted_bundles"][0][
        "stream_payload_sha256"]["rgb"] = "0" * 64
    _tamper_output.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")

_atexit.register(_tamper_embedded_report)
'''
            fixture.rosbag_impl.write_text(original + tamper, encoding="utf-8")
            fixture.refresh_authority()
            result = fixture.run_cli()
            self.assertFalse(result["algorithm_validated"])
            self.assertIn(
                "isolated_probe_result_not_valid:background",
                result["failures"],
            )
            self.assertEqual({}, result["scene_reports"])


if __name__ == "__main__":
    unittest.main()
