"""Host-owned producer for ROS1 semantic field-evidence material.

The producer never joins a ROS graph and never authorizes delivery.  It
reopens an externally bound rosbag1/typed-frame/probe tuple, joins a raw
measurement ledger to the exact typed frame IDs, and emits the six semantic
artifacts consumed by :mod:`ros1_noetic_field_readiness`.

Production use additionally requires a source-owned external authority
anchor.  That anchor is deliberately unconfigured in the offline source
generation, so a production invocation fails before reading a request or
creating an output directory.  The explicit test-only path exists solely for
pure-software algorithm tests and always marks every artifact synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from typing import Tuple

from limo_cleanup_perception import ros1_noetic_field_readiness as INTAKE


GATE_ID = 'ROS1_NOETIC_SEMANTIC_EVIDENCE_PRODUCER_V1'
AUTHORITY_MARKER = 'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_AUTHORITY_V1'
REQUEST_MARKER = 'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_REQUEST_V1'
LEDGER_MARKER = 'LIMO_ROS1_NOETIC_SEMANTIC_MEASUREMENT_LEDGER_V1'
REPORT_MARKER = 'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_REPORT_V1'
AUTHORITY_INDEX_MARKER = (
    'LIMO_ROS1_NOETIC_SEMANTIC_PRODUCER_AUTHORITY_INDEX_V1')
PRODUCTION_MODE = 'production_semantic_material'
TEST_ONLY_MODE = 'test_only_semantic_algorithm'

# These values may only be populated by a later source generation that also
# ships an out-of-band, host-owned trust anchor.  CLI-supplied values never
# substitute for this source-owned production selection.
PRODUCTION_AUTHORITY_INDEX_PATH: Optional[str] = None
PRODUCTION_AUTHORITY_INDEX_SIZE_BYTES: Optional[int] = None
PRODUCTION_AUTHORITY_INDEX_SHA256: Optional[str] = None

IDENTITY_KEYS = {'path', 'size_bytes', 'sha256'}
AUTHORITY_INDEX_KEYS = {
    'schema_version', 'marker', 'index_id', 'scope', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'scene_set',
    'authorities'}
AUTHORITY_KEYS = {
    'schema_version', 'marker', 'authority_id', 'scope', 'test_only',
    'read_only', 'authorizes_motion', 'publishes_ros_messages',
    'request_identity', 'producer_source', 'field_readiness_source',
    'canonical_source_admission', 'field_install_evidence',
    'model_manifest', 'model_artifacts', 'model_set_sha256',
    'ground_truth_review_authority', 'measurement_reference_authority',
    'allowed_output_root'}
REQUEST_KEYS = {
    'schema_version', 'marker', 'request_id', 'mode', 'read_only',
    'authorizes_motion', 'publishes_ros_messages', 'scene', 'capture_id',
    'task_id', 'raw_bag', 'probe_artifact', 'typed_frames',
    'typed_raw_binding', 'measurement_ledger',
    'canonical_source_admission', 'field_install_evidence',
    'model_manifest', 'model_artifacts', 'model_set_sha256',
    'ground_truth_review_authority', 'measurement_reference_authority',
    'output_directory'}
LEDGER_KEYS = {
    'schema_version', 'marker', 'scene', 'capture_id', 'task_id',
    'raw_bag', 'probe_artifact', 'typed_frames', 'typed_raw_binding',
    'canonical_source_admission', 'field_install_evidence',
    'model_manifest', 'model_artifacts', 'model_set_sha256',
    'ground_truth_review_authority', 'measurement_reference_authority',
    'ground_truth_operator_id', 'ground_truth_reviewer_id',
    'extrinsics', 'records'}
EXTRINSICS_INPUT_KEYS = {
    'source_frame', 'target_frame', 'translation_m', 'rotation_xyzw',
    'measurement_method', 'operator_id', 'reviewer_id',
    'measured_at_unix_sec', 'reviewed_at_unix_sec'}
LEDGER_RECORD_KEYS = {
    'sequence', 'stamp_ns', 'bundle_id', 'typed_frame_sha256',
    'rgb_payload_sha256', 'annotations', 'observations',
    'inference_started_unix_sec', 'inference_ended_unix_sec'}
OBSERVATION_INPUT_KEYS = {
    'observation_id', 'camera_xyz_m', 'reference_xyz_m',
    'reference_depth_m'}
GROUND_TRUTH_REVIEW_KEYS = {
    'schema_version', 'marker', 'scope', 'scene', 'capture_id', 'task_id',
    'raw_bag', 'typed_frames', 'operator_id', 'reviewer_id',
    'reviewed_at_unix_sec', 'synthetic_test_only'}
MEASUREMENT_REFERENCE_KEYS = {
    'schema_version', 'marker', 'scope', 'scene', 'capture_id', 'task_id',
    'raw_bag', 'probe_artifact', 'typed_frames', 'extrinsics_operator_id',
    'extrinsics_reviewer_id', 'measurement_method', 'observation_ids',
    'authorized_at_unix_sec', 'synthetic_test_only'}

OUTPUT_NAMES = {
    'ground_truth': 'ground_truth.json',
    'extrinsics_reference': 'extrinsics_reference.json',
    'tf_records': 'tf_records.json',
    'xyz_records': 'xyz_records.json',
    'depth_records': 'depth_records.json',
    'latency_records': 'latency_records.json',
}
REPORT_NAME = 'semantic_producer_report.json'


class ProducerError(ValueError):
    """Stable fail-closed producer error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProducerError('semantic_producer_duplicate_json_key')
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise ProducerError('semantic_producer_nonfinite_json_number:' + value)


def _strict_json(raw: bytes, code: str) -> Any:
    try:
        return json.loads(
            raw.decode('utf-8'), object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite)
    except ProducerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProducerError(code) from error


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n')


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and value == value.lower()
        and all(character in '0123456789abcdef' for character in value))


def _valid_identity(value: Any) -> bool:
    return (
        isinstance(value, Mapping) and set(value) == IDENTITY_KEYS
        and isinstance(value.get('path'), str) and value['path']
        and Path(value['path']).is_absolute()
        and type(value.get('size_bytes')) is int
        and value['size_bytes'] >= 0
        and _valid_sha256(value.get('sha256')))


def _read_identity_bytes(value: Mapping[str, Any], code: str) -> bytes:
    if not _valid_identity(value):
        raise ProducerError(code)
    try:
        expected_path = Path(value['path']).resolve(strict=True)
        actual = INTAKE.regular_file_identity(expected_path)
        if dict(value) != actual:
            raise ProducerError(code)
        with expected_path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode)
                    or int(getattr(before, 'st_nlink', 1)) != 1):
                raise ProducerError(code)
            raw = stream.read()
            after = os.fstat(stream.fileno())
        digest = hashlib.sha256(raw).hexdigest()
        if (before.st_size != after.st_size
                or getattr(before, 'st_dev', None)
                != getattr(after, 'st_dev', None)
                or getattr(before, 'st_ino', None)
                != getattr(after, 'st_ino', None)
                or getattr(before, 'st_mtime_ns', None)
                != getattr(after, 'st_mtime_ns', None)
                or len(raw) != value['size_bytes']
                or digest != value['sha256']):
            raise ProducerError(code)
        return raw
    except ProducerError:
        raise
    except (INTAKE.IntakeError, OSError, RuntimeError, ValueError) as error:
        raise ProducerError(code) from error


def _load_identity_json(value: Mapping[str, Any], code: str) -> Any:
    return _strict_json(_read_identity_bytes(value, code), code)


def _load_identity_jsonl(value: Mapping[str, Any], code: str) -> List[Any]:
    raw = _read_identity_bytes(value, code)
    lines = raw.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ProducerError(code)
    return [_strict_json(line, code) for line in lines]


def _text(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value) and value == value.strip()
        and '\x00' not in value)


def _finite(value: Any, minimum: float = None) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value))
        and (minimum is None or float(value) >= minimum))


def _integer(value: Any, minimum: int = None) -> bool:
    return type(value) is int and (minimum is None or value >= minimum)


def _vector(value: Any, length: int) -> bool:
    return (
        isinstance(value, list) and len(value) == length
        and all(_finite(item) for item in value))


def _same_vector(first: Sequence[float], second: Sequence[float],
                 tolerance: float = 1e-6) -> bool:
    return (
        len(first) == len(second)
        and all(abs(float(left) - float(right)) <= tolerance
                for left, right in zip(first, second)))


def _source_owned_production_index_anchor() -> Mapping[str, Any]:
    values = (
        PRODUCTION_AUTHORITY_INDEX_PATH,
        PRODUCTION_AUTHORITY_INDEX_SIZE_BYTES,
        PRODUCTION_AUTHORITY_INDEX_SHA256)
    if (values[0] is None or values[1] is None or values[2] is None):
        raise ProducerError(
            'semantic_producer_production_authority_not_anchored')
    anchor = {
        'path': values[0], 'size_bytes': values[1], 'sha256': values[2]}
    if not _valid_identity(anchor):
        raise ProducerError(
            'semantic_producer_production_authority_index_invalid')
    return anchor


def _validate_authority_index(value: Any) -> Mapping[str, Any]:
    authorities = value.get('authorities') if isinstance(value, Mapping) else None
    if (not isinstance(value, Mapping) or set(value) != AUTHORITY_INDEX_KEYS
            or value.get('schema_version') != 1
            or value.get('marker') != AUTHORITY_INDEX_MARKER
            or not _text(value.get('index_id'))
            or value.get('scope')
            != 'ros1_noetic_semantic_producer_authority_index'
            or value.get('read_only') is not True
            or value.get('authorizes_motion') is not False
            or value.get('publishes_ros_messages') is not False
            or value.get('scene_set') != list(INTAKE.SCENES)
            or not isinstance(authorities, Mapping)
            or list(authorities) != list(INTAKE.SCENES)
            or any(not _valid_identity(identity)
                   for identity in authorities.values())
            or len({identity['path'] for identity in authorities.values()})
            != len(INTAKE.SCENES)
            or len({(identity['size_bytes'], identity['sha256'])
                    for identity in authorities.values()})
            != len(INTAKE.SCENES)):
        raise ProducerError(
            'semantic_producer_production_authority_index_invalid')
    return dict(value)


def load_production_authority_index() -> Mapping[str, Any]:
    """Load the source-selected four-scene authority index."""
    identity = _source_owned_production_index_anchor()
    value = _load_identity_json(
        identity, 'semantic_producer_production_authority_index_invalid')
    return {
        'identity': dict(identity),
        'payload': _validate_authority_index(value),
    }


def _expected_authority_selection(
        authority_path: Path, size_bytes: int, sha256: str,
        test_only: bool) -> Tuple[
            Mapping[str, Any], Optional[Mapping[str, Any]], Optional[str]]:
    declared = {
        'path': str(Path(authority_path).absolute()),
        'size_bytes': size_bytes,
        'sha256': sha256,
    }
    if not _valid_identity(declared):
        raise ProducerError('semantic_producer_authority_identity_mismatch')
    if test_only:
        return declared, None, None
    index = load_production_authority_index()
    matches = [
        scene for scene, identity in index['payload']['authorities'].items()
        if identity == declared]
    if len(matches) != 1:
        raise ProducerError('semantic_producer_authority_identity_mismatch')
    return declared, index['identity'], matches[0]


def _validate_output_root(path_value: Any) -> Path:
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise ProducerError('semantic_producer_output_root_invalid')
    try:
        path = Path(path_value).resolve(strict=True)
        metadata = os.lstat(str(path))
        if (not stat.S_ISDIR(metadata.st_mode)
                or INTAKE._path_has_linklike_component(path)):
            raise ProducerError('semantic_producer_output_root_invalid')
        return path
    except ProducerError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ProducerError('semantic_producer_output_root_invalid') from error


def _validate_provenance_identity(
        authority: Mapping[str, Any], request: Mapping[str, Any],
        ledger: Mapping[str, Any], role: str, failure: str) -> None:
    expected = authority.get(role)
    if request.get(role) != expected or ledger.get(role) != expected:
        raise ProducerError(failure)
    _read_identity_bytes(expected, failure)


def _validate_model_provenance(
        authority: Mapping[str, Any], request: Mapping[str, Any],
        ledger: Mapping[str, Any]) -> None:
    artifacts = authority.get('model_artifacts')
    if (not isinstance(artifacts, Mapping)
            or set(artifacts) != set(INTAKE.MODEL_CLASSES)
            or request.get('model_artifacts') != artifacts
            or ledger.get('model_artifacts') != artifacts
            or request.get('model_manifest') != authority.get('model_manifest')
            or ledger.get('model_manifest') != authority.get('model_manifest')
            or request.get('model_set_sha256')
            != authority.get('model_set_sha256')
            or ledger.get('model_set_sha256')
            != authority.get('model_set_sha256')):
        raise ProducerError('semantic_producer_model_provenance_invalid')
    _read_identity_bytes(
        authority.get('model_manifest'),
        'semantic_producer_model_provenance_invalid')
    hashes = {}
    for name in INTAKE.MODEL_CLASSES:
        _read_identity_bytes(
            artifacts.get(name),
            'semantic_producer_model_provenance_invalid')
        hashes[name] = artifacts[name]['sha256']
    if INTAKE._model_set_sha256(hashes) != authority.get('model_set_sha256'):
        raise ProducerError('semantic_producer_model_provenance_invalid')


def _validate_measurement_authorities(
        authority: Mapping[str, Any], request: Mapping[str, Any],
        ledger: Mapping[str, Any], test_only: bool) -> None:
    for role in (
            'ground_truth_review_authority',
            'measurement_reference_authority'):
        if (request.get(role) != authority.get(role)
                or ledger.get(role) != authority.get(role)):
            raise ProducerError(
                'semantic_producer_measurement_authority_invalid')
    review = _load_identity_json(
        authority['ground_truth_review_authority'],
        'semantic_producer_measurement_authority_invalid')
    measurement = _load_identity_json(
        authority['measurement_reference_authority'],
        'semantic_producer_measurement_authority_invalid')
    operator = ledger.get('ground_truth_operator_id')
    reviewer = ledger.get('ground_truth_reviewer_id')
    if (not isinstance(review, Mapping) or set(review) != GROUND_TRUTH_REVIEW_KEYS
            or review.get('schema_version') != 1
            or review.get('marker')
            != 'LIMO_ROS1_GROUND_TRUTH_REVIEW_AUTHORITY_V1'
            or review.get('scope') != 'independent_ground_truth_review'
            or review.get('scene') != request['scene']
            or review.get('capture_id') != request['capture_id']
            or review.get('task_id') != request['task_id']
            or review.get('raw_bag') != request['raw_bag']
            or review.get('typed_frames') != request['typed_frames']
            or review.get('operator_id') != operator
            or review.get('reviewer_id') != reviewer
            or review.get('synthetic_test_only') is not test_only
            or not _finite(review.get('reviewed_at_unix_sec'), 0.0)):
        raise ProducerError('semantic_producer_measurement_authority_invalid')
    extrinsics = ledger.get('extrinsics')
    observation_ids = sorted({
        item.get('observation_id')
        for record in ledger.get('records', []) if isinstance(record, Mapping)
        for item in record.get('observations', []) if isinstance(item, Mapping)
        and _text(item.get('observation_id'))})
    if (not isinstance(measurement, Mapping)
            or set(measurement) != MEASUREMENT_REFERENCE_KEYS
            or measurement.get('schema_version') != 1
            or measurement.get('marker')
            != 'LIMO_ROS1_MEASUREMENT_REFERENCE_AUTHORITY_V1'
            or measurement.get('scope')
            != 'independent_extrinsics_xyz_depth_reference'
            or measurement.get('scene') != request['scene']
            or measurement.get('capture_id') != request['capture_id']
            or measurement.get('task_id') != request['task_id']
            or measurement.get('raw_bag') != request['raw_bag']
            or measurement.get('probe_artifact')
            != request['probe_artifact']
            or measurement.get('typed_frames') != request['typed_frames']
            or not isinstance(extrinsics, Mapping)
            or measurement.get('extrinsics_operator_id')
            != extrinsics.get('operator_id')
            or measurement.get('extrinsics_reviewer_id')
            != extrinsics.get('reviewer_id')
            or measurement.get('measurement_method')
            != extrinsics.get('measurement_method')
            or measurement.get('observation_ids') != observation_ids
            or measurement.get('synthetic_test_only') is not test_only
            or not _finite(measurement.get('authorized_at_unix_sec'), 0.0)):
        raise ProducerError('semantic_producer_measurement_authority_invalid')


def _load_authority(
        authority_path: Path, expected_identity: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Any]:
    if Path(expected_identity['path']) != Path(authority_path).absolute():
        raise ProducerError('semantic_producer_authority_identity_mismatch')
    authority = _load_identity_json(
        expected_identity, 'semantic_producer_authority_identity_mismatch')
    if (not isinstance(authority, Mapping)
            or set(authority) != AUTHORITY_KEYS
            or authority.get('schema_version') != 1
            or authority.get('marker') != AUTHORITY_MARKER
            or authority.get('scope')
            != 'ros1_noetic_semantic_evidence_producer'
            or authority.get('test_only') is not test_only
            or authority.get('read_only') is not True
            or authority.get('authorizes_motion') is not False
            or authority.get('publishes_ros_messages') is not False
            or not _text(authority.get('authority_id'))
            or not _valid_identity(authority.get('request_identity'))
            or not _valid_sha256(authority.get('model_set_sha256'))):
        raise ProducerError('semantic_producer_authority_schema_invalid')
    expected_source = INTAKE.regular_file_identity(Path(__file__))
    expected_readiness = INTAKE.regular_file_identity(Path(INTAKE.__file__))
    if (authority.get('producer_source') != expected_source
            or authority.get('field_readiness_source') != expected_readiness):
        raise ProducerError('semantic_producer_source_provenance_invalid')
    _validate_output_root(authority.get('allowed_output_root'))
    return authority


def _load_request(
        request_path: Path, authority: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Any]:
    expected = authority['request_identity']
    if Path(expected['path']) != Path(request_path).absolute():
        raise ProducerError('semantic_producer_request_identity_mismatch')
    request = _load_identity_json(
        expected, 'semantic_producer_request_identity_mismatch')
    if (not isinstance(request, Mapping) or set(request) != REQUEST_KEYS
            or request.get('schema_version') != 1
            or request.get('marker') != REQUEST_MARKER
            or request.get('mode')
            != (TEST_ONLY_MODE if test_only else PRODUCTION_MODE)
            or request.get('read_only') is not True
            or request.get('authorizes_motion') is not False
            or request.get('publishes_ros_messages') is not False
            or request.get('scene') not in INTAKE.SCENES
            or not _text(request.get('request_id'))
            or not _text(request.get('capture_id'))
            or not _text(request.get('task_id'))):
        raise ProducerError('semantic_producer_request_schema_invalid')
    return request


def _validate_authority_scene(
        request: Mapping[str, Any], selected_scene: Optional[str],
        test_only: bool) -> None:
    if test_only:
        if selected_scene is not None:
            raise ProducerError('semantic_producer_test_seam_forbidden')
        return
    if selected_scene not in INTAKE.SCENES or request.get(
            'scene') != selected_scene:
        raise ProducerError('semantic_producer_authority_scene_mismatch')


def _validate_input_identities(
        request: Mapping[str, Any], ledger: Mapping[str, Any]) -> None:
    for role, code in (
            ('raw_bag', 'semantic_producer_raw_bag_identity_mismatch'),
            ('probe_artifact',
             'semantic_producer_probe_artifact_identity_mismatch'),
            ('typed_frames',
             'semantic_producer_typed_frames_identity_mismatch'),
            ('typed_raw_binding',
             'semantic_producer_typed_raw_binding_invalid')):
        if request.get(role) != ledger.get(role):
            raise ProducerError(code)
        _read_identity_bytes(request.get(role), code)
    raw_path = Path(request['raw_bag']['path'])
    raw_bytes = _read_identity_bytes(
        request['raw_bag'], 'semantic_producer_raw_bag_identity_mismatch')
    if raw_path.suffix != '.bag' or not raw_bytes.startswith(b'#ROSBAG V2.0\n'):
        raise ProducerError('semantic_producer_raw_bag_identity_mismatch')


def _load_ledger(
        request: Mapping[str, Any], authority: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Any]:
    ledger = _load_identity_json(
        request.get('measurement_ledger'),
        'semantic_producer_measurement_ledger_identity_mismatch')
    if (not isinstance(ledger, Mapping) or set(ledger) != LEDGER_KEYS
            or ledger.get('schema_version') != 1
            or ledger.get('marker') != LEDGER_MARKER
            or ledger.get('scene') != request['scene']
            or ledger.get('capture_id') != request['capture_id']
            or ledger.get('task_id') != request['task_id']
            or not isinstance(ledger.get('records'), list)):
        raise ProducerError('semantic_producer_measurement_ledger_invalid')
    _validate_input_identities(request, ledger)
    _validate_provenance_identity(
        authority, request, ledger, 'canonical_source_admission',
        'semantic_producer_source_provenance_invalid')
    _validate_provenance_identity(
        authority, request, ledger, 'field_install_evidence',
        'semantic_producer_install_provenance_invalid')
    _validate_model_provenance(authority, request, ledger)
    operator = ledger.get('ground_truth_operator_id')
    reviewer = ledger.get('ground_truth_reviewer_id')
    if not _text(operator) or not _text(reviewer) or operator == reviewer:
        raise ProducerError('semantic_producer_ground_truth_review_invalid')
    extrinsics = ledger.get('extrinsics')
    if (not isinstance(extrinsics, Mapping)
            or set(extrinsics) != EXTRINSICS_INPUT_KEYS):
        raise ProducerError('semantic_producer_extrinsics_input_invalid')
    if (not _text(extrinsics.get('operator_id'))
            or not _text(extrinsics.get('reviewer_id'))
            or extrinsics['operator_id'] == extrinsics['reviewer_id']):
        raise ProducerError('semantic_producer_extrinsics_input_invalid')
    _validate_measurement_authorities(
        authority, request, ledger, test_only)
    if test_only is False and any(
            text.startswith('fixture') or 'synthetic' in text.lower()
            for text in (
                operator, reviewer, extrinsics['operator_id'],
                extrinsics['reviewer_id'],
                str(extrinsics.get('measurement_method', '')))):
        raise ProducerError('semantic_producer_test_seam_forbidden')
    return ledger


def _validate_probe(
        request: Mapping[str, Any], test_only: bool) -> Mapping[str, Any]:
    probe = _load_identity_json(
        request['probe_artifact'],
        'semantic_producer_probe_artifact_identity_mismatch')
    report = probe.get('formal_report') if isinstance(probe, Mapping) else None
    bundles = report.get('accepted_bundles') if isinstance(
        report, Mapping) else None
    tf_graph = report.get('tf_graph') if isinstance(report, Mapping) else None
    if (not isinstance(probe, Mapping)
            or set(probe) != INTAKE.PROBE_ARTIFACT_KEYS
            or probe.get('schema_version') != 1
            or probe.get('marker') != INTAKE.PROBE_ARTIFACT_MARKER
            or probe.get('read_only') is not True
            or probe.get('authorizes_motion') is not False
            or probe.get('publishes_ros_messages') is not False
            or probe.get('delivery_ready') is not False
            or probe.get('bag_identity') != request['raw_bag']
            or probe.get('capture_id') != request['capture_id']
            or probe.get('scene') != request['scene']
            or probe.get('test_only') is not test_only
            or probe.get('algorithm_validated') is not True
            or probe.get('formal_acceptance') is not False
            or probe.get('not_in_four_scene_denominator') is not True
            or not isinstance(report, Mapping)
            or report.get('storage_identifier') != 'rosbag1-v2'
            or report.get('mode') != 'formal_camera_only'
            or report.get('inspection_passed') is not True
            or report.get('formal_acceptance') is not (not test_only)
            or report.get('shared_graph') is not False
            or report.get('mixed_tf') is not False
            or report.get('delivery_ready') is not False
            or report.get('capture_id') != request['capture_id']
            or report.get('scene') != request['scene']
            or not isinstance(bundles, list) or not bundles
            or not isinstance(tf_graph, Mapping)
            or tf_graph.get('camera_only') is not True
            or not isinstance(tf_graph.get('transforms'), list)
            or not tf_graph['transforms']):
        raise ProducerError('semantic_producer_probe_artifact_invalid')
    return probe


def _frame_context(
        request: Mapping[str, Any], probe: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Any]:
    try:
        frames = _load_identity_jsonl(
            request['typed_frames'],
            'semantic_producer_typed_frames_identity_mismatch')
        scene = {
            'capture_id': request['capture_id'],
            'task_id': request['task_id'],
        }
        frame_report = INTAKE._validate_frames(
            frames, request['scene'], scene,
            {'model_set_sha256': request['model_set_sha256']},
            1 if test_only else INTAKE.MIN_PRODUCTION_SCENE_FRAMES)
        binding = _load_identity_json(
            request['typed_raw_binding'],
            'semantic_producer_typed_raw_binding_invalid')
        frame_report = dict(frame_report)
        frame_report.update(INTAKE._validate_typed_raw(
            binding, request['scene'], scene,
            {'model_set_sha256': request['model_set_sha256']},
            frame_report, probe, test_only))
        return frame_report
    except ProducerError:
        raise
    except INTAKE.IntakeError as error:
        code = error.code
        if code.startswith('typed_frame'):
            raise ProducerError(
                'semantic_producer_typed_frame_join_invalid') from error
        raise ProducerError(
            'semantic_producer_typed_raw_binding_invalid') from error


def _ledger_record_map(
        ledger: Mapping[str, Any], frame_report: Mapping[str, Any]
        ) -> Mapping[Tuple[int, int, str], Mapping[str, Any]]:
    result = {}
    frame_keys = set(frame_report['frames'])
    for record in ledger['records']:
        if not isinstance(record, Mapping) or set(record) != LEDGER_RECORD_KEYS:
            raise ProducerError('semantic_producer_measurement_record_invalid')
        key = (
            record.get('sequence'), record.get('stamp_ns'),
            record.get('bundle_id'))
        if (not _integer(key[0], 1) or not _integer(key[1], 1)
                or not _valid_sha256(key[2]) or key not in frame_keys
                or key in result):
            raise ProducerError('semantic_producer_measurement_coverage_invalid')
        result[key] = record
    if set(result) != frame_keys:
        raise ProducerError('semantic_producer_measurement_coverage_invalid')
    return result


def _validate_extrinsics(ledger: Mapping[str, Any]) -> Mapping[str, Any]:
    value = ledger['extrinsics']
    translation = value.get('translation_m')
    rotation = value.get('rotation_xyzw')
    measured = value.get('measured_at_unix_sec')
    reviewed = value.get('reviewed_at_unix_sec')
    if (value.get('source_frame') != 'camera_color_optical_frame'
            or value.get('target_frame') != 'base_link'
            or not _vector(translation, 3) or not _vector(rotation, 4)
            or abs(math.sqrt(sum(float(item) ** 2 for item in rotation)) - 1.0)
            > 1e-6
            or not _text(value.get('measurement_method'))
            or not _finite(measured, 0.0)
            or not _finite(reviewed, measured)):
        raise ProducerError('semantic_producer_extrinsics_input_invalid')
    return value


def _measurement_observations(
        record: Mapping[str, Any], targets: Mapping[str, Mapping[str, Any]]
        ) -> Mapping[str, Mapping[str, Any]]:
    values = record.get('observations')
    if not isinstance(values, list):
        raise ProducerError('semantic_producer_measurement_record_invalid')
    result = {}
    for value in values:
        observation_id = value.get('observation_id') if isinstance(
            value, Mapping) else None
        if (not isinstance(value, Mapping)
                or set(value) != OBSERVATION_INPUT_KEYS
                or observation_id not in targets or observation_id in result
                or not _vector(value.get('camera_xyz_m'), 3)
                or not _vector(value.get('reference_xyz_m'), 3)
                or not _finite(value.get('reference_depth_m'), 0.0)
                or float(value['reference_depth_m']) <= 0.0):
            raise ProducerError('semantic_producer_observation_measurement_invalid')
        result[observation_id] = value
    if set(result) != set(targets):
        raise ProducerError('semantic_producer_observation_coverage_invalid')
    return result


def _common(
        request: Mapping[str, Any], test_only: bool,
        report_kind: str) -> Mapping[str, Any]:
    return {
        'schema_version': 1,
        'scene': request['scene'],
        'capture_id': request['capture_id'],
        'task_id': request['task_id'],
        'ros1_field_install_sha256': request['field_install_evidence'][
            'sha256'],
        'model_binding_sha256': request['model_set_sha256'],
        'synthetic_test_only': test_only,
        'report_kind': report_kind,
    }


def _build_outputs(
        request: Mapping[str, Any], ledger: Mapping[str, Any],
        frame_report: Mapping[str, Any], probe: Mapping[str, Any],
        test_only: bool) -> Mapping[str, Mapping[str, Any]]:
    records = _ledger_record_map(ledger, frame_report)
    extrinsics_input = _validate_extrinsics(ledger)
    transform_payload = {
        'source_frame': extrinsics_input['source_frame'],
        'target_frame': extrinsics_input['target_frame'],
        'translation_m': extrinsics_input['translation_m'],
        'rotation_xyzw': extrinsics_input['rotation_xyzw'],
    }
    transform_sha = INTAKE._canonical_sha256(transform_payload)
    extrinsics = {
        **_common(
            request, test_only,
            INTAKE.ARTIFACT_MARKERS['extrinsics_reference']),
        **transform_payload,
        'transform_sha256': transform_sha,
        'measurement_method': extrinsics_input['measurement_method'],
        'operator_id': extrinsics_input['operator_id'],
        'reviewer_id': extrinsics_input['reviewer_id'],
        'measured_at_unix_sec': extrinsics_input['measured_at_unix_sec'],
        'reviewed_at_unix_sec': extrinsics_input['reviewed_at_unix_sec'],
    }
    raw_transform = INTAKE._raw_camera_transform(
        frame_report['tf_graph'], 'camera_color_optical_frame',
        request['scene'])
    ground_records = []
    tf_records = []
    xyz_records = []
    depth_records = []
    latency_records = []
    for key in sorted(frame_report['frames']):
        frame = frame_report['frames'][key][1]
        raw = frame_report['raw_by_frame'][key]
        material = records[key]
        targets = {item['observation_id']: item for item in frame['targets']}
        observations = _measurement_observations(material, targets)
        if (material.get('typed_frame_sha256')
                != INTAKE._canonical_sha256(frame)
                or material.get('rgb_payload_sha256')
                != raw.get('stream_payload_sha256', {}).get('rgb')):
            raise ProducerError('semantic_producer_typed_frame_join_invalid')
        annotations = material.get('annotations')
        if not isinstance(annotations, list):
            raise ProducerError('semantic_producer_ground_truth_input_invalid')
        ground_records.append({
            'sequence': key[0], 'stamp_ns': key[1], 'bundle_id': key[2],
            'typed_frame_sha256': INTAKE._canonical_sha256(frame),
            'rgb_payload_sha256': material['rgb_payload_sha256'],
            'annotations': annotations,
        })
        transforms = []
        for observation_id in sorted(targets):
            target = targets[observation_id]
            measurement = observations[observation_id]
            camera_xyz = measurement['camera_xyz_m']
            output_xyz = INTAKE._transform_point(
                camera_xyz, extrinsics_input['translation_m'],
                extrinsics_input['rotation_xyzw'])
            typed_xyz = [
                float(target['position'][axis]) for axis in ('x', 'y', 'z')]
            if (not _same_vector(output_xyz, typed_xyz)
                    or abs(float(camera_xyz[2]) - float(target['depth_m']))
                    > 1e-6):
                raise ProducerError('semantic_producer_tf_recompute_invalid')
            transforms.append({
                'observation_id': observation_id,
                'input_position_m': camera_xyz,
                'output_position_m': output_xyz,
                'extrinsics_transform_sha256': transform_sha,
            })
            reference_xyz = measurement['reference_xyz_m']
            xyz_error = math.sqrt(sum(
                (float(left) - float(right)) ** 2
                for left, right in zip(reference_xyz, typed_xyz)))
            xyz_records.append({
                'sequence': key[0], 'stamp_ns': key[1],
                'bundle_id': key[2], 'observation_id': observation_id,
                'reference_xyz_m': reference_xyz,
                'measured_xyz_m': typed_xyz,
                'error_m': xyz_error,
            })
            reference_depth = float(measurement['reference_depth_m'])
            measured_depth = float(target['depth_m'])
            valid_pixels = target['depth_valid_pixels']
            total_pixels = target['depth_total_pixels']
            ratio = float(target['depth_valid_ratio'])
            valid = (
                measured_depth > 0.0 and valid_pixels >= 1
                and total_pixels >= 1 and valid_pixels <= total_pixels
                and ratio >= INTAKE.MIN_DEPTH_VALID_RATE)
            depth_records.append({
                'sequence': key[0], 'stamp_ns': key[1],
                'bundle_id': key[2], 'observation_id': observation_id,
                'reference_depth_m': reference_depth,
                'measured_depth_m': measured_depth,
                'valid_pixels': valid_pixels,
                'total_pixels': total_pixels,
                'valid_ratio': ratio,
                'valid': valid,
                'error_m': abs(measured_depth - reference_depth),
            })
        tf_records.append({
            'sequence': key[0], 'stamp_ns': key[1], 'bundle_id': key[2],
            'topic': raw_transform['topic'],
            'message_id': raw_transform['message_id'],
            'connection_id': raw_transform['connection_id'],
            'transform_index': raw_transform['transform_index'],
            'callerid': raw_transform['callerid'],
            'transform_stamp_ns': raw_transform['stamp_ns'],
            'parent_frame_id': raw_transform['parent_frame_id'],
            'child_frame_id': raw_transform['child_frame_id'],
            'translation_m': raw_transform['translation_m'],
            'rotation_xyzw': raw_transform['rotation_xyzw'],
            'serialized_sha256': raw_transform['serialized_sha256'],
            'lookup_source_frame': frame['frame_id'],
            'lookup_target_frame': 'base_link',
            'lookup_succeeded': True,
            'transform_applied': True,
            'output_frame': 'base_link',
            'extrinsics_transform_sha256': transform_sha,
            'target_transforms': transforms,
        })
        started = material.get('inference_started_unix_sec')
        ended = material.get('inference_ended_unix_sec')
        sensor = key[1] / 1e9
        collected = frame['received_unix_sec']
        if (not _finite(started, sensor) or not _finite(ended, started)
                or float(ended) > float(collected)):
            raise ProducerError('semantic_producer_latency_input_invalid')
        latency_records.append({
            'sequence': key[0], 'stamp_ns': key[1], 'bundle_id': key[2],
            'sensor_stamp_sec': sensor,
            'inference_started_unix_sec': float(started),
            'inference_ended_unix_sec': float(ended),
            'collector_received_unix_sec': float(collected),
            'sync_span_sec': frame['sync_span_sec'],
            'processing_latency_sec': float(ended) - float(started),
            'transport_latency_sec': float(collected) - sensor,
            'end_to_end_latency_sec': float(collected) - sensor,
        })
    ground_map = {
        (item['sequence'], item['stamp_ns'], item['bundle_id']): item
        for item in ground_records}
    class_metrics = INTAKE._class_metrics(
        ground_map, frame_report['frames'])
    xyz_errors = [item['error_m'] for item in xyz_records]
    depth_errors = [item['error_m'] for item in depth_records]
    latency_end = [item['end_to_end_latency_sec'] for item in latency_records]
    latency_processing = [
        item['processing_latency_sec'] for item in latency_records]
    latency_sync = [item['sync_span_sec'] for item in latency_records]
    outputs = {
        'ground_truth': {
            **_common(
                request, test_only,
                INTAKE.ARTIFACT_MARKERS['ground_truth']),
            'complete': True,
            'unique_frames': len(ground_records),
            'annotation_count': sum(
                len(item['annotations']) for item in ground_records),
            'class_metrics': class_metrics,
            'records': ground_records,
        },
        'extrinsics_reference': extrinsics,
        'tf_records': {
            **_common(
                request, test_only, INTAKE.ARTIFACT_MARKERS['tf_records']),
            'source_frame': 'camera_color_optical_frame',
            'target_frame': 'base_link',
            'transform_applied': True,
            'mixed_tf': False,
            'tf_valid_frames': len(tf_records),
            'xyz_valid_frames': len(tf_records),
            'records': tf_records,
        },
        'xyz_records': {
            **_common(
                request, test_only, INTAKE.ARTIFACT_MARKERS['xyz_records']),
            'not_applicable': not bool(xyz_records),
            'sample_count': len(xyz_records),
            'max_error_m': max(xyz_errors) if xyz_errors else None,
            'p95_error_m': INTAKE._p95(xyz_errors),
            'records': xyz_records,
        },
        'depth_records': {
            **_common(
                request, test_only,
                INTAKE.ARTIFACT_MARKERS['depth_records']),
            'not_applicable': not bool(depth_records),
            'sample_count': len(depth_records),
            'valid_rate': (
                sum(1 for item in depth_records if item['valid'])
                / len(depth_records) if depth_records else None),
            'max_error_m': max(depth_errors) if depth_errors else None,
            'p95_error_m': INTAKE._p95(depth_errors),
            'records': depth_records,
        },
        'latency_records': {
            **_common(
                request, test_only,
                INTAKE.ARTIFACT_MARKERS['latency_records']),
            'sample_count': len(latency_records),
            'max_latency_sec': max(latency_end),
            'p95_end_to_end_sec': INTAKE._p95(latency_end),
            'p95_processing_sec': INTAKE._p95(latency_processing),
            'p95_sync_sec': INTAKE._p95(latency_sync),
            'records': latency_records,
        },
    }
    try:
        INTAKE._validate_semantic_records(
            request['scene'], {
                'capture_id': request['capture_id'],
                'task_id': request['task_id']}, {
                'field_install_evidence': request['field_install_evidence'],
                'model_set_sha256': request['model_set_sha256']},
            frame_report, outputs, test_only)
    except INTAKE.IntakeError as error:
        raise ProducerError(
            'semantic_producer_consumer_recompute_failed:' + error.code
        ) from error
    return outputs


def _validate_output_directory(
        request: Mapping[str, Any], authority: Mapping[str, Any],
        output_directory: Path) -> Path:
    if (not Path(output_directory).is_absolute()
            or request.get('output_directory') != str(output_directory)):
        raise ProducerError('semantic_producer_output_path_mismatch')
    output_root = _validate_output_root(authority['allowed_output_root'])
    candidate = Path(output_directory).absolute()
    try:
        candidate.parent.resolve(strict=True).relative_to(output_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProducerError('semantic_producer_output_root_escape') from error
    if candidate.exists():
        raise ProducerError('semantic_producer_output_not_exclusive')
    if INTAKE._path_has_linklike_component(candidate.parent):
        raise ProducerError('semantic_producer_output_root_invalid')
    return candidate


def produce_semantic_evidence(
        request_path: Path, authority_path: Path,
        authority_expected_identity: Mapping[str, Any],
        output_directory: Path, *, test_only: bool = False
        ) -> Mapping[str, Any]:
    """Produce one scene's semantic material without ROS or hardware I/O."""
    if not isinstance(test_only, bool):
        raise ProducerError('semantic_producer_test_seam_forbidden')
    authority_index_identity = None
    selected_scene = None
    if not test_only:
        index = load_production_authority_index()
        matches = [
            scene for scene, identity in index['payload']['authorities'].items()
            if identity == dict(authority_expected_identity)]
        if len(matches) != 1:
            raise ProducerError('semantic_producer_authority_identity_mismatch')
        authority_index_identity = index['identity']
        selected_scene = matches[0]
    authority = _load_authority(
        Path(authority_path), authority_expected_identity, test_only)
    request = _load_request(Path(request_path), authority, test_only)
    _validate_authority_scene(request, selected_scene, test_only)
    ledger = _load_ledger(request, authority, test_only)
    probe = _validate_probe(request, test_only)
    frame_report = _frame_context(request, probe, test_only)
    outputs = _build_outputs(
        request, ledger, frame_report, probe, test_only)
    destination = _validate_output_directory(
        request, authority, Path(output_directory))

    encoded = {role: _json_bytes(value) for role, value in outputs.items()}
    destination.mkdir()
    incomplete_marker = destination / 'INCOMPLETE_DO_NOT_USE'
    with incomplete_marker.open('xb') as stream:
        stream.write(b'partial semantic producer output; never admit\n')
        stream.flush()
        os.fsync(stream.fileno())
    output_identities = {}
    try:
        for role in OUTPUT_NAMES:
            path = destination / OUTPUT_NAMES[role]
            with path.open('xb') as stream:
                stream.write(encoded[role])
                stream.flush()
                os.fsync(stream.fileno())
            output_identities[role] = INTAKE.regular_file_identity(path)
        report = {
            'schema_version': 1,
            'marker': REPORT_MARKER,
            'gate_id': GATE_ID,
            'mode': TEST_ONLY_MODE if test_only else PRODUCTION_MODE,
            'read_only': True,
            'authorizes_motion': False,
            'publishes_ros_messages': False,
            'producer_material_validated': True,
            'formal_acceptance': False,
            'not_in_four_scene_denominator': True,
            'field_evidence_admitted': False,
            'delivery_ready': False,
            'synthetic_test_only': test_only,
            'authority_identity': dict(authority_expected_identity),
            'authority_index_identity': authority_index_identity,
            'producer_source_identity': authority['producer_source'],
            'field_readiness_source_identity': authority[
                'field_readiness_source'],
            'request_identity': authority['request_identity'],
            'measurement_ledger_identity': request['measurement_ledger'],
            'raw_bag_identity': request['raw_bag'],
            'probe_artifact_identity': request['probe_artifact'],
            'typed_frames_identity': request['typed_frames'],
            'typed_raw_binding_identity': request['typed_raw_binding'],
            'canonical_source_admission': request[
                'canonical_source_admission'],
            'field_install_evidence': request['field_install_evidence'],
            'model_manifest': request['model_manifest'],
            'model_artifacts': request['model_artifacts'],
            'model_set_sha256': request['model_set_sha256'],
            'ground_truth_review_authority': request[
                'ground_truth_review_authority'],
            'measurement_reference_authority': request[
                'measurement_reference_authority'],
            'scene': request['scene'],
            'capture_id': request['capture_id'],
            'task_id': request['task_id'],
            'typed_frame_count': len(frame_report['frames']),
            'observation_count': len(frame_report['observations']),
            'outputs': output_identities,
            'output_commit_state': 'COMPLETE_EXCLUSIVE_SET',
            'failures': (
                ['synthetic_test_only_not_formal_evidence']
                if test_only else []),
        }
        report_path = destination / REPORT_NAME
        with report_path.open('xb') as stream:
            stream.write(_json_bytes(report))
            stream.flush()
            os.fsync(stream.fileno())
        # A crash or write failure above intentionally leaves the marker in
        # place.  The host consumer requires the exact completed filename set
        # and therefore cannot mistake a partial directory for valid material.
        incomplete_marker.unlink()
        result = dict(report)
        result['report_identity'] = INTAKE.regular_file_identity(report_path)
        return result
    except (OSError, RuntimeError, INTAKE.IntakeError) as error:
        raise ProducerError(
            'semantic_producer_output_write_failed:'
            + type(error).__name__) from error


def parse_args(args: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Produce host-owned ROS1 semantic evidence material.')
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--authority', type=Path, required=True)
    parser.add_argument('--authority-size-bytes', type=int, required=True)
    parser.add_argument('--authority-sha256', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--test-only', action='store_true')
    tokens = list(sys.argv[1:] if args is None else args)
    option_names = {
        '--request', '--authority', '--authority-size-bytes',
        '--authority-sha256', '--output-directory', '--test-only'}
    if any(tokens.count(option) > 1 for option in option_names):
        parser.error('duplicate option is forbidden')
    return parser.parse_args(tokens)


def _failure_report(code: str, test_only: bool) -> Mapping[str, Any]:
    return {
        'schema_version': 1,
        'marker': REPORT_MARKER,
        'gate_id': GATE_ID,
        'mode': TEST_ONLY_MODE if test_only else PRODUCTION_MODE,
        'read_only': True,
        'authorizes_motion': False,
        'publishes_ros_messages': False,
        'producer_material_validated': False,
        'formal_acceptance': False,
        'not_in_four_scene_denominator': True,
        'field_evidence_admitted': False,
        'delivery_ready': False,
        'failures': [code],
    }


def main(args: Optional[Sequence[str]] = None) -> int:
    """CLI entry.  Production anchor rejection precedes all input reads."""
    parsed = parse_args(args)
    try:
        expected, _, _ = _expected_authority_selection(
            parsed.authority, parsed.authority_size_bytes,
            parsed.authority_sha256, parsed.test_only)
        result = produce_semantic_evidence(
            parsed.request, parsed.authority, expected,
            parsed.output_directory, test_only=parsed.test_only)
        sys.stdout.buffer.write(_json_bytes(result))
        return 0
    except (ProducerError, OSError, RuntimeError, TypeError, ValueError) as error:
        code = (error.code if isinstance(error, ProducerError)
                else 'semantic_producer_cli_failure:' + type(error).__name__)
        sys.stdout.buffer.write(_json_bytes(
            _failure_report(code, parsed.test_only)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
