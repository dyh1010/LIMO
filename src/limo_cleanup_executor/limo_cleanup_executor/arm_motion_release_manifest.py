"""Strict offline release gate for reviewed arm motion parameters.

The validator is deliberately independent of ROS and actuator libraries.  It
only evaluates a versioned JSON document and derives ``release_ready`` from
the supplied evidence; callers cannot assert that value in the manifest.
"""

import argparse
import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = 2
EXPECTED_ARM_MODEL = 'myCobot 280 M5'
REQUIRED_POSE_ROLES = (
    'pre_grasp',
    'grasp',
    'verify_lift',
    'transport',
    'pre_release',
    'release',
    'retreat',
)

_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
_UTC_TIMESTAMP = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
_MAX_EVIDENCE_JSON_BYTES = 1024 * 1024
_MAX_BOUND_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_VENDOR_CALL_DEADLINE_S = 60.0
_WINDOWS_RESERVED_PATH_NAMES = frozenset((
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
))


class ArmMotionManifestError(ValueError):
    """Raised when a release manifest is structurally unsafe or ambiguous."""


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArmMotionManifestError(
                'duplicate JSON key: {}'.format(key))
        result[key] = value
    return result


def _reject_nonfinite_constant(value):
    raise ArmMotionManifestError(
        'non-finite JSON constant: {}'.format(value))


def _clone_json_value(value, label='manifest'):
    """Copy only exact JSON-domain types without invoking user hooks."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ArmMotionManifestError(
                '{} contains a non-finite number'.format(label))
        return value
    if type(value) is list:
        return [
            _clone_json_value(item, '{}[{}]'.format(label, index))
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ArmMotionManifestError(
                    '{} contains a non-string key'.format(label))
            result[key] = _clone_json_value(
                item, '{}.{}'.format(label, key))
        return result
    raise ArmMotionManifestError(
        '{} contains a non-JSON value'.format(label))


def loads_manifest(payload):
    """Parse strict JSON, rejecting duplicate keys and NaN/Infinity."""
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except ArmMotionManifestError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise ArmMotionManifestError(
            'arm motion manifest must be valid strict JSON') from exc


def load_manifest(path):
    """Read one local manifest without importing ROS or a vendor library."""
    return loads_manifest(Path(path).read_text(encoding='utf-8'))


def _prepare_artifact_root(value, issues):
    if value is None:
        _issue(issues, 'an explicit local artifact_root is required')
        return None
    if not isinstance(value, (str, Path)):
        raise ArmMotionManifestError(
            'artifact_root must be an absolute filesystem path')
    raw = str(value)
    normalized = raw.replace('\\', '/').casefold()
    if (
            normalized == '/dev'
            or normalized.startswith('/dev/')
            or raw.startswith('\\\\.\\')
            or raw.startswith('\\\\?\\')):
        raise ArmMotionManifestError(
            'device and special namespace artifact roots are forbidden')
    root = Path(value)
    if not root.is_absolute():
        raise ArmMotionManifestError('artifact_root must be absolute')
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArmMotionManifestError(
            'artifact_root is unavailable: {}'.format(exc)) from exc
    if not root.is_dir():
        raise ArmMotionManifestError('artifact_root must be a directory')
    return root


def _safe_relative_artifact_path(value, label):
    if type(value) is not str or not value.strip():
        raise ArmMotionManifestError(
            '{} must be a non-empty normalized relative path'.format(label))
    if value != value.strip() or '\\' in value or '\x00' in value:
        raise ArmMotionManifestError(
            '{} must use normalized forward slashes'.format(label))
    if re.match(r'^[A-Za-z]:', value):
        raise ArmMotionManifestError(
            '{} must not be drive-qualified'.format(label))
    parsed = PurePosixPath(value)
    if (
            parsed.is_absolute()
            or any(part in ('', '.', '..') for part in parsed.parts)):
        raise ArmMotionManifestError(
            '{} must remain inside artifact_root'.format(label))
    for part in parsed.parts:
        if ':' in part or part.endswith((' ', '.')):
            raise ArmMotionManifestError(
                '{} contains ambiguous path syntax'.format(label))
        if part.split('.', 1)[0].upper() in _WINDOWS_RESERVED_PATH_NAMES:
            raise ArmMotionManifestError(
                '{} contains a reserved device name'.format(label))
    return value


def _read_strict_json_artifact(payload, label):
    if type(payload) is not bytes:
        raise ArmMotionManifestError(
            '{} must be supplied as verified artifact bytes'.format(label))
    try:
        if len(payload) > _MAX_EVIDENCE_JSON_BYTES:
            raise ArmMotionManifestError(
                '{} exceeds the offline evidence size limit'.format(label))
        text = payload.decode('utf-8')
    except UnicodeError as exc:
        raise ArmMotionManifestError(
            '{} must be UTF-8 JSON'.format(label)) from exc
    return loads_manifest(text)


def _read_bound_artifact(path, label):
    """Read one ordinary file once; hash and parsers share these exact bytes."""
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    if nofollow:
        flags |= nofollow
    descriptor = None
    try:
        descriptor = os.open(str(path), flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ArmMotionManifestError(
                '{} must be an ordinary file'.format(label))
        if metadata.st_size > _MAX_BOUND_ARTIFACT_BYTES:
            raise ArmMotionManifestError(
                '{} exceeds the bound artifact size limit'.format(label))
        chunks = []
        remaining = _MAX_BOUND_ARTIFACT_BYTES + 1
        while remaining > 0:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        payload = b''.join(chunks)
        if len(payload) > _MAX_BOUND_ARTIFACT_BYTES:
            raise ArmMotionManifestError(
                '{} exceeds the bound artifact size limit'.format(label))
        return payload
    except OSError as exc:
        raise ArmMotionManifestError(
            '{} could not be read'.format(label)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _mapping(value, label):
    if type(value) is not dict:
        raise ArmMotionManifestError(
            '{} must be a JSON object'.format(label))
    return value


def _exact_keys(value, expected, label):
    mapping = _mapping(value, label)
    actual = set(mapping)
    missing = sorted(set(expected) - actual)
    unknown = sorted(actual - set(expected))
    if missing or unknown:
        raise ArmMotionManifestError(
            '{} keys mismatch; missing={}, unknown={}'.format(
                label, missing, unknown))
    return mapping


def _issue(issues, detail):
    if detail not in issues:
        issues.append(detail)


def _required_string(mapping, key, issues, label):
    value = mapping[key]
    if value is None:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    if type(value) is not str or not value.strip():
        raise ArmMotionManifestError(
            '{} must be a non-empty string or null'.format(label))
    mapping[key] = value.strip()
    return mapping[key]


def _sha256(mapping, key, issues, label):
    value = mapping[key]
    if value is None:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ArmMotionManifestError(
            '{} must be exactly 64 hexadecimal characters or null'.format(
                label))
    mapping[key] = value.lower()
    return mapping[key]


def _finite_number(value, label, positive=False, nonnegative=False):
    if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))):
        raise ArmMotionManifestError(
            '{} must be a finite number'.format(label))
    resolved = float(value)
    if positive and resolved <= 0.0:
        raise ArmMotionManifestError(
            '{} must be positive'.format(label))
    if nonnegative and resolved < 0.0:
        raise ArmMotionManifestError(
            '{} must be non-negative'.format(label))
    return resolved


def _required_number(
        mapping, key, issues, label, positive=False, nonnegative=False):
    value = mapping[key]
    if value is None:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    return _finite_number(
        value, label, positive=positive, nonnegative=nonnegative)


def _required_integer(mapping, key, issues, label, lower=None, upper=None):
    value = mapping[key]
    if value is None:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    if type(value) is not int:
        raise ArmMotionManifestError(
            '{} must be a native integer or null'.format(label))
    if lower is not None and value < lower:
        raise ArmMotionManifestError(
            '{} must be at least {}'.format(label, lower))
    if upper is not None and value > upper:
        raise ArmMotionManifestError(
            '{} must be at most {}'.format(label, upper))
    return value


def _required_vector(mapping, key, length, issues, label):
    value = mapping[key]
    if value is None:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    if type(value) is not list or len(value) != length:
        raise ArmMotionManifestError(
            '{} must contain exactly {} values or be null'.format(
                label, length))
    return tuple(
        _finite_number(item, '{}[{}]'.format(label, index))
        for index, item in enumerate(value)
    )


def _limit_pairs(mapping, key, issues, label):
    value = mapping[key]
    if type(value) is not list:
        raise ArmMotionManifestError(
            '{} must be a JSON array'.format(label))
    if not value:
        _issue(issues, '{} is unresolved'.format(label))
        return None
    if len(value) != 6:
        raise ArmMotionManifestError(
            '{} must contain exactly six pairs'.format(label))
    result = []
    for index, pair in enumerate(value, start=1):
        item_label = '{}[{}]'.format(label, index)
        if type(pair) is not list or len(pair) != 2:
            raise ArmMotionManifestError(
                '{} must be a two-value array'.format(item_label))
        lower = _finite_number(pair[0], item_label + '.lower')
        upper = _finite_number(pair[1], item_label + '.upper')
        if lower >= upper:
            raise ArmMotionManifestError(
                '{} must be ordered lower < upper'.format(item_label))
        result.append((lower, upper))
    return tuple(result)


def _validate_release_binding(section, issues):
    section = _exact_keys(section, (
        'runtime_release_id',
        'release_manifest_sha256',
    ), 'release_binding')
    runtime_release_id = _required_string(
        section, 'runtime_release_id', issues,
        'release_binding.runtime_release_id')
    _sha256(
        section, 'release_manifest_sha256', issues,
        'release_binding.release_manifest_sha256')
    return runtime_release_id


def _validate_capability_declaration(value, issues, label):
    value = _exact_keys(value, (
        'enforced',
        'artifact',
        'artifact_sha256',
    ), label)
    enforced = value['enforced']
    if enforced is None:
        _issue(issues, '{}.enforced is unresolved'.format(label))
    elif type(enforced) is not bool:
        raise ArmMotionManifestError(
            '{}.enforced must be a native boolean or null'.format(label))
    elif not enforced:
        _issue(issues, '{}.enforced must be true'.format(label))
    artifact = value['artifact']
    if artifact is None:
        _issue(issues, '{}.artifact is unresolved'.format(label))
    else:
        _safe_relative_artifact_path(artifact, label + '.artifact')
    _sha256(
        value, 'artifact_sha256', issues, label + '.artifact_sha256')


def _validate_real_backend_gate(section, issues):
    section = _exact_keys(section, (
        'bounded_call_capability',
        'deadline_enforcement_capability',
        'native_cancel_capability',
        'independent_stop_channel_capability',
        'persistent_safety_latch_capability',
    ), 'real_backend_gate')
    for key in (
            'bounded_call_capability',
            'deadline_enforcement_capability',
            'native_cancel_capability',
            'independent_stop_channel_capability',
            'persistent_safety_latch_capability'):
        _validate_capability_declaration(
            section[key], issues, 'real_backend_gate.' + key)


def _validate_artifact_declarations(artifacts, issues):
    if type(artifacts) is not list:
        raise ArmMotionManifestError('artifacts must be a JSON array')
    if not artifacts:
        _issue(issues, 'artifacts is unresolved')
        return {}
    by_hash = {}
    paths = set()
    for index, record in enumerate(artifacts):
        label = 'artifacts[{}]'.format(index)
        record = _exact_keys(record, ('path', 'sha256', 'claims'), label)
        path = _safe_relative_artifact_path(record['path'], label + '.path')
        sha256 = _sha256(record, 'sha256', issues, label + '.sha256')
        claims = record['claims']
        if type(claims) is not list or not claims:
            raise ArmMotionManifestError(
                '{}.claims must be a non-empty JSON array'.format(label))
        resolved_claims = []
        for claim_index, claim in enumerate(claims):
            if (
                    type(claim) is not str
                    or not claim.startswith('manifest.')
                    or not claim.endswith('_sha256')
                    or claim != claim.strip()):
                raise ArmMotionManifestError(
                    '{}.claims[{}] must be an exact manifest SHA-256 path'
                    .format(label, claim_index))
            resolved_claims.append(claim)
        if len(set(resolved_claims)) != len(resolved_claims):
            raise ArmMotionManifestError(
                '{}.claims must be unique'.format(label))
        if path in paths:
            raise ArmMotionManifestError(
                'artifact paths must be unique')
        paths.add(path)
        if sha256 is not None:
            if sha256 in by_hash:
                raise ArmMotionManifestError(
                    'artifact SHA-256 values must be unique')
            by_hash[sha256] = {
                'path': path,
                'claims': tuple(resolved_claims),
            }
    return by_hash


def _collect_declared_sha256(value, label='manifest'):
    declared = []
    if type(value) is dict:
        for key, item in value.items():
            child_label = '{}.{}'.format(label, key)
            if key.endswith('_sha256') and item is not None:
                declared.append((child_label, item))
            declared.extend(_collect_declared_sha256(item, child_label))
    elif type(value) is list:
        for index, item in enumerate(value):
            declared.extend(_collect_declared_sha256(
                item, '{}[{}]'.format(label, index)))
    return declared


def _bind_artifacts(manifest, artifact_root, artifact_index, issues):
    if artifact_root is None:
        return {}
    verified = {}
    for sha256, record in artifact_index.items():
        relative = record['path']
        unresolved = artifact_root.joinpath(*PurePosixPath(relative).parts)
        try:
            if unresolved.is_symlink():
                _issue(
                    issues,
                    'artifact {} must not be a symbolic link'.format(relative))
                continue
            candidate = unresolved.resolve(strict=True)
        except (OSError, RuntimeError):
            _issue(issues, 'artifact {} is missing'.format(relative))
            continue
        try:
            candidate.relative_to(artifact_root)
        except ValueError:
            _issue(issues, 'artifact {} escapes artifact_root'.format(relative))
            continue
        if not candidate.is_file():
            _issue(
                issues,
                'artifact {} must be an ordinary file'.format(relative))
            continue
        try:
            payload = _read_bound_artifact(
                candidate, 'artifact {}'.format(relative))
            actual = hashlib.sha256(payload).hexdigest()
        except ArmMotionManifestError as exc:
            _issue(issues, str(exc))
            continue
        if actual != sha256:
            _issue(
                issues,
                'artifact {} SHA-256 does not match'.format(relative))
            continue
        verified[sha256] = {
            'path': candidate,
            'payload': payload,
        }

    declared = _collect_declared_sha256(manifest)
    declared_labels = {label for label, unused_sha256 in declared}
    claimed_labels = {}
    for sha256, record in artifact_index.items():
        for claim in record['claims']:
            if claim in claimed_labels:
                raise ArmMotionManifestError(
                    'artifact claims must be globally unique: {}'.format(claim))
            claimed_labels[claim] = sha256
            if claim not in declared_labels:
                raise ArmMotionManifestError(
                    'artifact claim does not name a declared SHA-256: {}'.format(
                        claim))
    for label, sha256 in declared:
        if label.startswith('manifest.artifacts['):
            continue
        if sha256 not in artifact_index:
            _issue(
                issues,
                '{} is not declared by artifacts'.format(label))
        elif sha256 not in verified:
            _issue(
                issues,
                '{} is not bound to a verified artifact'.format(label))
        elif claimed_labels.get(label) != sha256:
            _issue(
                issues,
                '{} is not explicitly claimed by its artifact'.format(label))
    return verified


def _exact_boolean(mapping, key, label):
    value = mapping[key]
    if type(value) is not bool:
        raise ArmMotionManifestError(
            '{} must be a native boolean'.format(label))
    return value


def _bounded_evidence_number(
        mapping, key, label, positive=True, maximum=None):
    value = _finite_number(mapping[key], label, positive=positive)
    if maximum is not None and value > maximum:
        raise ArmMotionManifestError(
            '{} exceeds the maximum releasable value'.format(label))
    return value


def _validate_execution_safety_evidence(
        evidence, issues, expected_runtime_release_id,
        expected_release_manifest_sha256=None,
        expected_acceleration_profile_manifest_sha256=None,
        expected_approved_speed_grades=None):
    evidence = _exact_keys(evidence, (
        'schema_version',
        'runtime_release_id',
        'release_manifest_sha256',
        'acceleration_profile_manifest_sha256',
        'approved_speed_grades',
        'vendor_call_deadlines',
        'execution_domains',
        'cancellation_capability',
        'hung_motion_send_probe',
        'persistent_safety_latch',
        'trace',
    ), 'execution_safety_evidence')
    if type(evidence['schema_version']) is not int:
        raise ArmMotionManifestError(
            'execution_safety_evidence.schema_version must be a native integer')
    if evidence['schema_version'] != 1:
        raise ArmMotionManifestError(
            'unsupported execution_safety_evidence.schema_version')
    runtime_release_id = evidence['runtime_release_id']
    if type(runtime_release_id) is not str or not runtime_release_id.strip():
        raise ArmMotionManifestError(
            'execution_safety_evidence.runtime_release_id must be non-empty')
    if runtime_release_id != runtime_release_id.strip():
        raise ArmMotionManifestError(
            'execution_safety_evidence.runtime_release_id must be exact')
    if (
            expected_runtime_release_id is not None
            and runtime_release_id != expected_runtime_release_id):
        _issue(
            issues,
            'execution safety evidence runtime_release_id does not match '
            'release_binding.runtime_release_id')
    for key in (
            'release_manifest_sha256',
            'acceleration_profile_manifest_sha256'):
        value = evidence[key]
        if (
                type(value) is not str
                or len(value) != 64
                or any(character not in '0123456789abcdef'
                       for character in value)):
            raise ArmMotionManifestError(
                'execution_safety_evidence.{} must be an exact lowercase '
                'SHA-256'.format(key))
    for key, expected in (
            ('release_manifest_sha256',
             expected_release_manifest_sha256),
            ('acceleration_profile_manifest_sha256',
             expected_acceleration_profile_manifest_sha256)):
        if expected is not None and evidence[key] != expected:
            _issue(
                issues,
                'execution safety evidence {} does not match the approved '
                'manifest binding'.format(key))
    grades = evidence['approved_speed_grades']
    if type(grades) is not list or not grades:
        raise ArmMotionManifestError(
            'execution_safety_evidence.approved_speed_grades must be a '
            'non-empty JSON array')
    if any(type(grade) is not int or not 1 <= grade <= 100 for grade in grades):
        raise ArmMotionManifestError(
            'execution safety approved speed grades must be integers in 1..100')
    if grades != sorted(set(grades)):
        raise ArmMotionManifestError(
            'execution safety approved speed grades must be unique and '
            'increasing')
    if (
            expected_approved_speed_grades is not None
            and grades != expected_approved_speed_grades):
        _issue(
            issues,
            'execution safety approved speed grades do not exactly match '
            'motion_profile.approved_speed_grades')

    deadlines = _exact_keys(evidence['vendor_call_deadlines'], (
        'deadline_enforced',
        'call_deadlines_s',
    ), 'execution_safety_evidence.vendor_call_deadlines')
    if not _exact_boolean(
            deadlines, 'deadline_enforced',
            'execution_safety_evidence.vendor_call_deadlines.deadline_enforced'):
        _issue(issues, 'vendor call deadlines are not enforced')
    required_calls = (
        'close',
        'get_angles',
        'get_coords',
        'get_end_type',
        'get_error_information',
        'get_fresh_mode',
        'get_joint_max',
        'get_joint_min',
        'get_reference_frame',
        'get_tool_reference',
        'is_all_servo_enable',
        'is_controller_connected',
        'is_moving',
        'is_paused',
        'is_power_on',
        'send_angles',
        'send_coords',
        'stop',
    )
    call_deadlines = _exact_keys(
        deadlines['call_deadlines_s'], required_calls,
        'execution_safety_evidence.vendor_call_deadlines.call_deadlines_s')
    for call in required_calls:
        _bounded_evidence_number(
            call_deadlines, call,
            'execution_safety_evidence.vendor_call_deadlines.'
            'call_deadlines_s.' + call,
            maximum=_MAX_VENDOR_CALL_DEADLINE_S)
    stop_deadline = float(call_deadlines['stop'])

    domains = _exact_keys(evidence['execution_domains'], (
        'motion_domain',
        'stop_domain',
        'independent_lock_domains',
    ), 'execution_safety_evidence.execution_domains')
    motion_domain = domains['motion_domain']
    stop_domain = domains['stop_domain']
    for key, value in (
            ('motion_domain', motion_domain), ('stop_domain', stop_domain)):
        if type(value) is not str or not value.strip() or value != value.strip():
            raise ArmMotionManifestError(
                'execution_safety_evidence.execution_domains.{} must be an '
                'exact non-empty string'.format(key))
    if motion_domain == stop_domain:
        _issue(issues, 'motion and STOP execution domains must be different')
    if not _exact_boolean(
            domains, 'independent_lock_domains',
            'execution_safety_evidence.execution_domains.'
            'independent_lock_domains'):
        _issue(issues, 'motion and STOP lock domains are not independent')

    cancellation = _exact_keys(evidence['cancellation_capability'], (
        'native_transport_cancel_enforced',
        'python_timeout_thread_used',
        'cancel_deadline_s',
        'cancel_completed',
        'cancel_elapsed_s',
        'cancelled_send_cannot_commit',
    ), 'execution_safety_evidence.cancellation_capability')
    if not _exact_boolean(
            cancellation, 'native_transport_cancel_enforced',
            'execution_safety_evidence.cancellation_capability.'
            'native_transport_cancel_enforced'):
        _issue(issues, 'native transport cancellation is not enforced')
    if _exact_boolean(
            cancellation, 'python_timeout_thread_used',
            'execution_safety_evidence.cancellation_capability.'
            'python_timeout_thread_used'):
        _issue(
            issues,
            'a Python timeout thread is not accepted as transport cancellation')
    cancel_deadline = _bounded_evidence_number(
        cancellation, 'cancel_deadline_s',
        'execution_safety_evidence.cancellation_capability.cancel_deadline_s',
        maximum=_MAX_VENDOR_CALL_DEADLINE_S)
    cancel_elapsed = _bounded_evidence_number(
        cancellation, 'cancel_elapsed_s',
        'execution_safety_evidence.cancellation_capability.cancel_elapsed_s',
        positive=False, maximum=_MAX_VENDOR_CALL_DEADLINE_S)
    if not _exact_boolean(
            cancellation, 'cancel_completed',
            'execution_safety_evidence.cancellation_capability.'
            'cancel_completed'):
        _issue(issues, 'native transport cancellation did not complete')
    if cancel_elapsed > cancel_deadline:
        _issue(issues, 'native transport cancellation missed its deadline')
    if not _exact_boolean(
            cancellation, 'cancelled_send_cannot_commit',
            'execution_safety_evidence.cancellation_capability.'
            'cancelled_send_cannot_commit'):
        _issue(issues, 'a cancelled send can still commit a motion command')

    probe = _exact_keys(evidence['hung_motion_send_probe'], (
        'command_id',
        'send_hung',
        'stop_completed',
        'stop_elapsed_s',
        'stop_deadline_s',
        'stop_completed_before_send_release',
    ), 'execution_safety_evidence.hung_motion_send_probe')
    probe_command_id = probe['command_id']
    if (
            type(probe_command_id) is not str
            or not probe_command_id.strip()
            or probe_command_id != probe_command_id.strip()):
        raise ArmMotionManifestError(
            'execution_safety_evidence.hung_motion_send_probe.command_id '
            'must be exact and non-empty')
    if not _exact_boolean(
            probe, 'send_hung',
            'execution_safety_evidence.hung_motion_send_probe.send_hung'):
        _issue(issues, 'hung motion send probe did not exercise a hung send')
    if not _exact_boolean(
            probe, 'stop_completed',
            'execution_safety_evidence.hung_motion_send_probe.stop_completed'):
        _issue(issues, 'STOP did not complete during hung motion send')
    stop_elapsed = _bounded_evidence_number(
        probe, 'stop_elapsed_s',
        'execution_safety_evidence.hung_motion_send_probe.stop_elapsed_s',
        positive=False, maximum=_MAX_VENDOR_CALL_DEADLINE_S)
    probe_deadline = _bounded_evidence_number(
        probe, 'stop_deadline_s',
        'execution_safety_evidence.hung_motion_send_probe.stop_deadline_s',
        maximum=_MAX_VENDOR_CALL_DEADLINE_S)
    if stop_elapsed > probe_deadline or probe_deadline != stop_deadline:
        _issue(issues, 'hung-send STOP did not satisfy the declared deadline')
    if not _exact_boolean(
            probe, 'stop_completed_before_send_release',
            'execution_safety_evidence.hung_motion_send_probe.'
            'stop_completed_before_send_release'):
        _issue(issues, 'hung motion send blocked STOP completion')

    latch = _exact_keys(evidence['persistent_safety_latch'], (
        'exclusive_create_enforced',
        'atomic_update_enforced',
        'generation_chain_enforced',
        'restart_restored_active_latch',
        'old_session_clear_rejected',
        'external_clearance_validator_required',
        'local_hashes_claim_authenticity',
    ), 'execution_safety_evidence.persistent_safety_latch')
    for key, detail in (
            ('exclusive_create_enforced',
             'persistent safety latch exclusive create is not enforced'),
            ('atomic_update_enforced',
             'persistent safety latch atomic update is not enforced'),
            ('generation_chain_enforced',
             'persistent safety latch generation chain is not enforced'),
            ('restart_restored_active_latch',
             'active persistent safety latch was not restored after restart'),
            ('old_session_clear_rejected',
             'an old session can clear the persistent safety latch'),
            ('external_clearance_validator_required',
             'persistent safety latch clearance lacks an external validator')):
        if not _exact_boolean(
                latch, key,
                'execution_safety_evidence.persistent_safety_latch.' + key):
            _issue(issues, detail)
    if _exact_boolean(
            latch, 'local_hashes_claim_authenticity',
            'execution_safety_evidence.persistent_safety_latch.'
            'local_hashes_claim_authenticity'):
        _issue(
            issues,
            'local hash-chain evidence must not claim cryptographic authenticity')

    trace = _exact_keys(evidence['trace'], (
        'command_id',
        'result_command_id',
        'timeout_command_id',
        'stop_command_id',
        'stationary_command_id',
        'ack_command_id',
        'interrupted_result_success',
        'stop_return_used_as_stationary_evidence',
        'stationary_samples',
        'stationary_dwell_s',
        'command_started_at_s',
        'timeout_at_s',
        'stop_requested_at_s',
        'stop_completed_at_s',
        'stationary_proven_at_s',
        'ack_at_s',
        'result_at_s',
    ), 'execution_safety_evidence.trace')
    command_id = trace['command_id']
    ids = [
        command_id,
        trace['result_command_id'],
        trace['timeout_command_id'],
        trace['stop_command_id'],
        trace['stationary_command_id'],
        trace['ack_command_id'],
        probe_command_id,
    ]
    if any(
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            for value in ids):
        raise ArmMotionManifestError(
            'execution safety trace IDs must be exact non-empty strings')
    if len(set(ids)) != 1:
        _issue(
            issues,
            'timeout, STOP, stationary, ACK and result evidence must share '
            'one command_id')
    if _exact_boolean(
            trace, 'interrupted_result_success',
            'execution_safety_evidence.trace.interrupted_result_success'):
        _issue(issues, 'an interrupted command result must be unsuccessful')
    if _exact_boolean(
            trace, 'stop_return_used_as_stationary_evidence',
            'execution_safety_evidence.trace.'
            'stop_return_used_as_stationary_evidence'):
        _issue(issues, 'STOP return must not be used as stationary evidence')
    samples = trace['stationary_samples']
    if type(samples) is not list or len(samples) < 3:
        _issue(issues, 'at least three stationary samples are required')
        samples = [] if type(samples) is not list else samples
    sample_ids = set()
    sample_times = []
    for index, sample in enumerate(samples):
        label = 'execution_safety_evidence.trace.stationary_samples[{}]'.format(
            index)
        sample = _exact_keys(sample, ('sample_id', 'time_s'), label)
        sample_id = sample['sample_id']
        if (
                type(sample_id) is not str
                or not sample_id.strip()
                or sample_id != sample_id.strip()):
            raise ArmMotionManifestError(
                '{}.sample_id must be exact and non-empty'.format(label))
        if sample_id in sample_ids:
            _issue(issues, 'stationary sample IDs must be unique')
        sample_ids.add(sample_id)
        sample_times.append(_bounded_evidence_number(
            sample, 'time_s', label + '.time_s', positive=False))
    if sample_times and any(
            current <= previous
            for previous, current in zip(sample_times, sample_times[1:])):
        _issue(issues, 'stationary sample times must be strictly increasing')
    dwell = _bounded_evidence_number(
        trace, 'stationary_dwell_s',
        'execution_safety_evidence.trace.stationary_dwell_s')
    stationary_at = _bounded_evidence_number(
        trace, 'stationary_proven_at_s',
        'execution_safety_evidence.trace.stationary_proven_at_s',
        positive=False)
    ack_at = _bounded_evidence_number(
        trace, 'ack_at_s',
        'execution_safety_evidence.trace.ack_at_s', positive=False)
    command_started_at = _bounded_evidence_number(
        trace, 'command_started_at_s',
        'execution_safety_evidence.trace.command_started_at_s',
        positive=False)
    timeout_at = _bounded_evidence_number(
        trace, 'timeout_at_s',
        'execution_safety_evidence.trace.timeout_at_s', positive=False)
    stop_requested_at = _bounded_evidence_number(
        trace, 'stop_requested_at_s',
        'execution_safety_evidence.trace.stop_requested_at_s',
        positive=False)
    stop_completed_at = _bounded_evidence_number(
        trace, 'stop_completed_at_s',
        'execution_safety_evidence.trace.stop_completed_at_s',
        positive=False)
    result_at = _bounded_evidence_number(
        trace, 'result_at_s',
        'execution_safety_evidence.trace.result_at_s', positive=False)
    if sample_times:
        observed_dwell = sample_times[-1] - sample_times[0]
        if observed_dwell + 1e-12 < dwell:
            _issue(issues, 'stationary samples do not span the declared dwell')
        if stationary_at < sample_times[-1]:
            _issue(
                issues,
                'stationary proof predates the final stationary sample')
    if ack_at <= stationary_at:
        _issue(issues, 'ACK must occur after stationary proof')
    if not (
            command_started_at <= timeout_at <= stop_requested_at
            <= stop_completed_at <= stationary_at < ack_at <= result_at):
        _issue(
            issues,
            'command, timeout, STOP, stationary, ACK and result timeline is '
            'not safely ordered')


def _validate_execution_safety_bindings(
        manifest, artifact_index, verified_artifacts, issues,
        runtime_release_id):
    gate = manifest['real_backend_gate']
    resolved_paths = []
    for key in (
            'bounded_call_capability',
            'deadline_enforcement_capability',
            'native_cancel_capability',
            'independent_stop_channel_capability',
            'persistent_safety_latch_capability'):
        label = 'real_backend_gate.' + key
        capability = gate[key]
        sha256 = capability['artifact_sha256']
        relative = capability['artifact']
        if sha256 is None or relative is None:
            continue
        indexed = artifact_index.get(sha256)
        if indexed is not None and indexed['path'] != relative:
            _issue(
                issues,
                '{} artifact path does not match artifacts[]'.format(label))
            continue
        artifact = verified_artifacts.get(sha256)
        if artifact is not None:
            resolved_paths.append(artifact)
    if not resolved_paths:
        return
    if len({item['path'] for item in resolved_paths}) != 1:
        _issue(
            issues,
            'real backend capabilities must bind one execution-safety artifact')
        return
    evidence = _read_strict_json_artifact(
        resolved_paths[0]['payload'], 'execution safety artifact')
    _validate_execution_safety_evidence(
        evidence,
        issues,
        runtime_release_id,
        manifest['release_binding']['release_manifest_sha256'],
        manifest['motion_profile'][
            'acceleration_profile_manifest_sha256'],
        manifest['motion_profile']['approved_speed_grades'],
    )


def _validate_acceleration_profile_artifact(
        manifest, verified_artifacts, issues, runtime_release_id,
        physical_limits):
    profile = manifest['motion_profile']
    sha256 = profile['acceleration_profile_manifest_sha256']
    if sha256 is None:
        return
    artifact = verified_artifacts.get(sha256)
    if artifact is None:
        return
    evidence = _read_strict_json_artifact(
        artifact['payload'], 'acceleration profile artifact')
    evidence = _exact_keys(evidence, (
        'schema_version',
        'runtime_release_id',
        'profile_id',
        'tool_revision',
        'max_speed_grade',
        'approved_speed_grades',
        'approved_tcp_modes',
        'max_joint_speed_deg_s',
        'max_tcp_speed_mm_s',
        'max_joint_acceleration_deg_s2',
        'max_tcp_acceleration_mm_s2',
        'max_joint_stop_distance_deg',
        'max_tcp_stop_distance_mm',
    ), 'acceleration_profile_artifact')
    if (
            type(evidence['schema_version']) is not int
            or evidence['schema_version'] != 1):
        raise ArmMotionManifestError(
            'acceleration_profile_artifact.schema_version must be exact '
            'integer 1')
    exact_fields = (
        ('runtime_release_id', runtime_release_id),
        ('profile_id', profile['profile_id']),
        ('tool_revision', profile['tool_revision']),
        ('max_speed_grade', profile['max_speed_grade']),
        ('approved_speed_grades', profile['approved_speed_grades']),
        ('approved_tcp_modes', profile['approved_tcp_modes']),
    )
    for key, expected in exact_fields:
        if evidence[key] != expected or type(evidence[key]) is not type(expected):
            _issue(
                issues,
                'acceleration profile artifact {} does not match '
                'motion_profile'.format(key))
    for key, expected in physical_limits.items():
        observed = _finite_number(
            evidence[key], 'acceleration_profile_artifact.' + key,
            positive=True)
        if expected is not None and observed != expected:
            _issue(
                issues,
                'acceleration profile artifact {} does not match '
                'motion_profile'.format(key))


def _validate_runtime_release_artifact(
        manifest, verified_artifacts, issues, runtime_release_id):
    binding = manifest['release_binding']
    sha256 = binding['release_manifest_sha256']
    if sha256 is None:
        return
    artifact = verified_artifacts.get(sha256)
    if artifact is None:
        return
    runtime = _read_strict_json_artifact(
        artifact['payload'], 'runtime release artifact')
    runtime = _exact_keys(runtime, (
        'schema_version',
        'runtime_release_id',
        'arm_model',
        'motion_profile_id',
        'acceleration_profile_manifest_sha256',
        'acceleration_profile_runtime_release_id',
        'bounded_call_capability',
        'deadline_enforcement_capability',
        'native_cancel_capability',
        'independent_stop_channel_capability',
        'persistent_safety_latch_capability',
    ), 'runtime_release_artifact')
    if type(runtime['schema_version']) is not int or runtime['schema_version'] != 1:
        raise ArmMotionManifestError(
            'runtime_release_artifact.schema_version must be exact integer 1')
    expected = {
        'runtime_release_id': runtime_release_id,
        'arm_model': manifest['arm_model'],
        'motion_profile_id': manifest['motion_profile']['profile_id'],
        'acceleration_profile_manifest_sha256': manifest[
            'motion_profile']['acceleration_profile_manifest_sha256'],
        'acceleration_profile_runtime_release_id': manifest[
            'motion_profile']['acceleration_profile_runtime_release_id'],
        'bounded_call_capability': manifest['real_backend_gate'][
            'bounded_call_capability']['enforced'],
        'deadline_enforcement_capability': manifest['real_backend_gate'][
            'deadline_enforcement_capability']['enforced'],
        'native_cancel_capability': manifest['real_backend_gate'][
            'native_cancel_capability']['enforced'],
        'independent_stop_channel_capability': manifest['real_backend_gate'][
            'independent_stop_channel_capability']['enforced'],
        'persistent_safety_latch_capability': manifest['real_backend_gate'][
            'persistent_safety_latch_capability']['enforced'],
    }
    for key, value in expected.items():
        if runtime[key] != value or type(runtime[key]) is not type(value):
            _issue(
                issues,
                'runtime release artifact {} does not match manifest'.format(
                    key))


def _validate_source_binding(source, issues):
    source = _exact_keys(source, (
        'interface_contract_sha256',
        'acceptance_contract_sha256',
        'gateway_policy_sha256',
        'collision_model_sha256',
    ), 'source_binding')
    for key in source:
        _sha256(source, key, issues, 'source_binding.' + key)


def _validate_tool(tool, issues):
    tool = _exact_keys(tool, (
        'model',
        'revision',
        'assembly_sha256',
        'mass_kg',
        'center_of_mass_mm',
        'inertia_kg_m2',
    ), 'tool')
    model = _required_string(tool, 'model', issues, 'tool.model')
    revision = _required_string(tool, 'revision', issues, 'tool.revision')
    _sha256(tool, 'assembly_sha256', issues, 'tool.assembly_sha256')
    _required_number(
        tool, 'mass_kg', issues, 'tool.mass_kg', positive=True)
    _required_vector(
        tool, 'center_of_mass_mm', 3, issues,
        'tool.center_of_mass_mm')
    inertia = _required_vector(
        tool, 'inertia_kg_m2', 6, issues, 'tool.inertia_kg_m2')
    if inertia is not None and any(value <= 0.0 for value in inertia[:3]):
        raise ArmMotionManifestError(
            'tool inertia diagonal values must be positive')
    return model, revision


def _validate_coordinate_contract(contract, issues):
    contract = _exact_keys(contract, (
        'reference_frame',
        'reference_frame_id',
        'end_type',
        'endpoint_frame_id',
        'controller_tool_reference',
        'flange_to_tcp',
        'translation_uncertainty_mm',
        'rotation_uncertainty_deg',
        'controller_readback_sha256',
        'tcp_measurement_sha256',
        'base_extrinsic_sha256',
    ), 'coordinate_contract')
    reference_frame = _required_integer(
        contract, 'reference_frame', issues,
        'coordinate_contract.reference_frame', lower=0, upper=1)
    frame_id = _required_string(
        contract, 'reference_frame_id', issues,
        'coordinate_contract.reference_frame_id')
    end_type = _required_integer(
        contract, 'end_type', issues,
        'coordinate_contract.end_type', lower=0, upper=1)
    endpoint = _required_string(
        contract, 'endpoint_frame_id', issues,
        'coordinate_contract.endpoint_frame_id')
    controller_tool = _required_vector(
        contract, 'controller_tool_reference', 6, issues,
        'coordinate_contract.controller_tool_reference')
    flange_to_tcp = _required_vector(
        contract, 'flange_to_tcp', 6, issues,
        'coordinate_contract.flange_to_tcp')
    _required_number(
        contract, 'translation_uncertainty_mm', issues,
        'coordinate_contract.translation_uncertainty_mm', positive=True)
    _required_number(
        contract, 'rotation_uncertainty_deg', issues,
        'coordinate_contract.rotation_uncertainty_deg', positive=True)
    for key in (
            'controller_readback_sha256',
            'tcp_measurement_sha256',
            'base_extrinsic_sha256'):
        _sha256(
            contract, key, issues, 'coordinate_contract.' + key)

    if reference_frame is not None and reference_frame != 0:
        _issue(issues, 'only the reviewed base reference frame is releasable')
    if frame_id is not None and frame_id != 'arm_base_link':
        _issue(issues, 'reference_frame_id must be arm_base_link')
    if end_type == 0:
        if endpoint is not None and endpoint != 'arm_flange':
            _issue(issues, 'flange end type must use arm_flange endpoint')
        if (
                controller_tool is not None
                and any(abs(value) > 1e-12 for value in controller_tool)):
            _issue(
                issues,
                'flange end type requires an explicit zero controller TCP')
    elif end_type == 1:
        if endpoint is not None and endpoint != 'gripper_tcp':
            _issue(issues, 'tool end type must use gripper_tcp endpoint')
        if (
                controller_tool is not None
                and flange_to_tcp is not None
                and controller_tool != flange_to_tcp):
            _issue(
                issues,
                'controller tool reference does not match flange_to_tcp')
    return frame_id, endpoint


def _validate_motion_profile(profile, issues, tool_revision):
    profile = _exact_keys(profile, (
        'profile_id',
        'tool_revision',
        'acceleration_profile_manifest_sha256',
        'acceleration_profile_runtime_release_id',
        'max_speed_grade',
        'approved_speed_grades',
        'approved_tcp_modes',
        'max_joint_speed_deg_s',
        'max_tcp_speed_mm_s',
        'max_joint_acceleration_deg_s2',
        'max_tcp_acceleration_mm_s2',
        'max_joint_stop_distance_deg',
        'max_tcp_stop_distance_mm',
        'path_mode_review_sha256',
        'approval_sha256',
        'cases',
    ), 'motion_profile')
    _required_string(
        profile, 'profile_id', issues, 'motion_profile.profile_id')
    profile_tool_revision = _required_string(
        profile, 'tool_revision', issues,
        'motion_profile.tool_revision')
    _sha256(
        profile, 'acceleration_profile_manifest_sha256', issues,
        'motion_profile.acceleration_profile_manifest_sha256')
    acceleration_runtime_release_id = _required_string(
        profile, 'acceleration_profile_runtime_release_id', issues,
        'motion_profile.acceleration_profile_runtime_release_id')
    max_speed = _required_integer(
        profile, 'max_speed_grade', issues,
        'motion_profile.max_speed_grade', lower=1, upper=100)
    _sha256(
        profile, 'approval_sha256', issues,
        'motion_profile.approval_sha256')
    _sha256(
        profile, 'path_mode_review_sha256', issues,
        'motion_profile.path_mode_review_sha256')

    physical_limits = {}
    for key in (
            'max_joint_speed_deg_s',
            'max_tcp_speed_mm_s',
            'max_joint_acceleration_deg_s2',
            'max_tcp_acceleration_mm_s2',
            'max_joint_stop_distance_deg',
            'max_tcp_stop_distance_mm'):
        physical_limits[key] = _required_number(
            profile, key, issues, 'motion_profile.' + key,
            positive=True)

    grades = profile['approved_speed_grades']
    if type(grades) is not list:
        raise ArmMotionManifestError(
            'motion_profile.approved_speed_grades must be a JSON array')
    for index, grade in enumerate(grades):
        if type(grade) is not int or not 1 <= grade <= 100:
            raise ArmMotionManifestError(
                'approved speed grade {} must be an integer in 1..100'
                .format(index))
    if not grades:
        _issue(issues, 'motion_profile.approved_speed_grades is unresolved')
    elif grades != sorted(set(grades)):
        raise ArmMotionManifestError(
            'approved speed grades must be unique and increasing')
    if max_speed is not None and grades and max_speed != max(grades):
        _issue(
            issues,
            'motion_profile.max_speed_grade does not match approved grades')

    tcp_modes = profile['approved_tcp_modes']
    if type(tcp_modes) is not list:
        raise ArmMotionManifestError(
            'motion_profile.approved_tcp_modes must be a JSON array')
    for index, mode in enumerate(tcp_modes):
        if type(mode) is not int or mode not in (0, 1):
            raise ArmMotionManifestError(
                'approved TCP mode {} must be native integer 0 or 1'
                .format(index))
    if not tcp_modes:
        _issue(issues, 'motion_profile.approved_tcp_modes is unresolved')
    elif tcp_modes != sorted(set(tcp_modes)):
        raise ArmMotionManifestError(
            'approved TCP modes must be unique and increasing')
    if (
            tool_revision is not None
            and profile_tool_revision is not None
            and tool_revision != profile_tool_revision):
        _issue(issues, 'motion profile tool revision does not match tool')

    cases = profile['cases']
    if type(cases) is not list:
        raise ArmMotionManifestError(
            'motion_profile.cases must be a JSON array')
    if not cases:
        _issue(issues, 'motion_profile.cases is unresolved')
        _issue(
            issues,
            'acceleration, speed and stopping-distance evidence is '
            'unresolved')
        return acceleration_runtime_release_id, physical_limits
    case_ids = set()
    represented_grades = set()
    represented_modes = set()
    case_keys = (
        'case_id',
        'speed_grade',
        'tcp_mode',
        'load_case',
        'pose_set',
        'measured_joint_speed_deg_s',
        'measured_tcp_speed_mm_s',
        'measured_joint_acceleration_deg_s2',
        'measured_tcp_acceleration_mm_s2',
        'measured_joint_stop_distance_deg',
        'measured_tcp_stop_distance_mm',
        'sample_count',
        'evidence_sha256',
    )
    measurement_to_limit = {
        'measured_joint_speed_deg_s': 'max_joint_speed_deg_s',
        'measured_tcp_speed_mm_s': 'max_tcp_speed_mm_s',
        'measured_joint_acceleration_deg_s2': (
            'max_joint_acceleration_deg_s2'),
        'measured_tcp_acceleration_mm_s2': (
            'max_tcp_acceleration_mm_s2'),
        'measured_joint_stop_distance_deg': (
            'max_joint_stop_distance_deg'),
        'measured_tcp_stop_distance_mm': 'max_tcp_stop_distance_mm',
    }
    measurement_keys = (
        'measured_joint_speed_deg_s',
        'measured_tcp_speed_mm_s',
        'measured_joint_acceleration_deg_s2',
        'measured_tcp_acceleration_mm_s2',
        'measured_joint_stop_distance_deg',
        'measured_tcp_stop_distance_mm',
    )
    for index, case in enumerate(cases):
        label = 'motion_profile.cases[{}]'.format(index)
        case = _exact_keys(case, case_keys, label)
        case_id = _required_string(case, 'case_id', issues, label + '.case_id')
        if case_id in case_ids:
            raise ArmMotionManifestError(
                'motion profile case ids must be unique')
        if case_id is not None:
            case_ids.add(case_id)
        grade = _required_integer(
            case, 'speed_grade', issues, label + '.speed_grade',
            lower=1, upper=100)
        if grade is not None:
            represented_grades.add(grade)
            if grades and grade not in grades:
                _issue(
                    issues,
                    '{} uses a non-approved speed grade'.format(label))
        mode = _required_integer(
            case, 'tcp_mode', issues, label + '.tcp_mode',
            lower=0, upper=1)
        if mode is not None and tcp_modes and mode not in tcp_modes:
            _issue(
                issues,
                '{} uses a non-approved TCP mode'.format(label))
        if mode is not None:
            represented_modes.add(mode)
        _required_string(case, 'load_case', issues, label + '.load_case')
        _required_string(case, 'pose_set', issues, label + '.pose_set')
        for key in measurement_keys:
            measured = _required_number(
                case, key, issues, label + '.' + key, positive=True)
            approved_limit = physical_limits[measurement_to_limit[key]]
            if (
                    measured is not None
                    and approved_limit is not None
                    and measured > approved_limit):
                _issue(
                    issues,
                    '{} exceeds motion_profile.{}'.format(
                        label + '.' + key,
                        measurement_to_limit[key]))
        sample_count = _required_integer(
            case, 'sample_count', issues, label + '.sample_count', lower=1)
        if sample_count is not None and sample_count < 3:
            _issue(issues, label + '.sample_count must show repeatability')
        _sha256(case, 'evidence_sha256', issues, label + '.evidence_sha256')
    for grade in grades:
        if grade not in represented_grades:
            _issue(
                issues,
                'approved speed grade {} has no measured case'.format(grade))
    for mode in tcp_modes:
        if mode not in represented_modes:
            _issue(
                issues,
                'approved TCP mode {} has no measured case'.format(mode))
    represented_pairs = {
        (case['speed_grade'], case['tcp_mode'])
        for case in cases
        if type(case['speed_grade']) is int
        and not isinstance(case['speed_grade'], bool)
        and type(case['tcp_mode']) is int
        and not isinstance(case['tcp_mode'], bool)
    }
    for grade in grades:
        for mode in tcp_modes:
            if (grade, mode) not in represented_pairs:
                _issue(
                    issues,
                    'approved speed grade {} / TCP mode {} has no '
                    'measured case'.format(grade, mode))
    return acceleration_runtime_release_id, physical_limits


def _validate_joint_limits(section, issues, controller_state):
    section = _exact_keys(section, (
        'required_fresh_mode',
        'controller_deg',
        'project_deg',
        'required_named_pose_margin_deg',
        'controller_readback_sha256',
        'collision_review_sha256',
    ), 'joint_limits')
    required_fresh_mode = _required_integer(
        section, 'required_fresh_mode', issues,
        'joint_limits.required_fresh_mode', lower=0, upper=1)
    controller = _limit_pairs(
        section, 'controller_deg', issues, 'joint_limits.controller_deg')
    project = _limit_pairs(
        section, 'project_deg', issues, 'joint_limits.project_deg')
    required_margin = _required_number(
        section, 'required_named_pose_margin_deg', issues,
        'joint_limits.required_named_pose_margin_deg', positive=True)
    _sha256(
        section, 'controller_readback_sha256', issues,
        'joint_limits.controller_readback_sha256')
    _sha256(
        section, 'collision_review_sha256', issues,
        'joint_limits.collision_review_sha256')
    if controller is not None and project is not None:
        for index, (controller_pair, project_pair) in enumerate(
                zip(controller, project), start=1):
            if (
                    project_pair[0] <= controller_pair[0]
                    or project_pair[1] >= controller_pair[1]):
                _issue(
                    issues,
                    'joint {} project limits are not a strict controller '
                    'subset'.format(index))
    if (
            required_fresh_mode is not None
            and controller_state['fresh_mode'] is not None
            and required_fresh_mode != controller_state['fresh_mode']):
        _issue(
            issues,
            'joint_limits.required_fresh_mode disagrees with controller '
            'state')
    return project, required_margin


def _validate_controller_state(section, issues):
    section = _exact_keys(section, (
        'controller_connected',
        'power_on',
        'moving',
        'paused',
        'error_code',
        'all_servos_enabled',
        'fresh_mode',
        'stationary_samples',
        'stationary_dwell_s',
        'stationary_joint_tolerance_deg',
        'state_max_age_s',
        'readback_sha256',
    ), 'controller_state')
    expected = {
        'controller_connected': 1,
        'power_on': 1,
        'moving': 0,
        'paused': 0,
        'error_code': 0,
        'all_servos_enabled': 1,
    }
    resolved = {}
    for key, required in expected.items():
        value = _required_integer(
            section, key, issues, 'controller_state.' + key)
        resolved[key] = value
        if value is not None and value != required:
            _issue(
                issues,
                'controller_state.{} must be exact integer {}'.format(
                    key, required))
    fresh_mode = _required_integer(
        section, 'fresh_mode', issues,
        'controller_state.fresh_mode', lower=0, upper=1)
    resolved['fresh_mode'] = fresh_mode
    samples = _required_integer(
        section, 'stationary_samples', issues,
        'controller_state.stationary_samples', lower=1)
    if samples is not None and samples < 3:
        _issue(
            issues,
            'controller_state.stationary_samples must be at least 3')
    _required_number(
        section, 'stationary_dwell_s', issues,
        'controller_state.stationary_dwell_s', positive=True)
    _required_number(
        section, 'stationary_joint_tolerance_deg', issues,
        'controller_state.stationary_joint_tolerance_deg', positive=True)
    _required_number(
        section, 'state_max_age_s', issues,
        'controller_state.state_max_age_s', positive=True)
    _sha256(
        section, 'readback_sha256', issues,
        'controller_state.readback_sha256')
    return resolved


def _validate_cartesian_limits(
        section, issues, reference_frame_id, endpoint_frame_id):
    section = _exact_keys(section, (
        'reference_frame_id',
        'endpoint_frame_id',
        'bounds',
        'workspace_review_sha256',
        'ik_collision_review_sha256',
    ), 'cartesian_limits')
    frame_id = _required_string(
        section, 'reference_frame_id', issues,
        'cartesian_limits.reference_frame_id')
    endpoint = _required_string(
        section, 'endpoint_frame_id', issues,
        'cartesian_limits.endpoint_frame_id')
    bounds = _limit_pairs(
        section, 'bounds', issues, 'cartesian_limits.bounds')
    _sha256(
        section, 'workspace_review_sha256', issues,
        'cartesian_limits.workspace_review_sha256')
    _sha256(
        section, 'ik_collision_review_sha256', issues,
        'cartesian_limits.ik_collision_review_sha256')
    if (
            frame_id is not None
            and reference_frame_id is not None
            and frame_id != reference_frame_id):
        _issue(issues, 'Cartesian and controller reference frames disagree')
    if (
            endpoint is not None
            and endpoint_frame_id is not None
            and endpoint != endpoint_frame_id):
        _issue(issues, 'Cartesian and controller endpoint frames disagree')
    return bounds


def _validate_named_poses(
        poses, issues, project_limits, required_margin, tool_revision):
    if type(poses) is not list:
        raise ArmMotionManifestError('named_poses must be a JSON array')
    if not poses:
        _issue(issues, 'named_poses is unresolved')
        return
    pose_keys = (
        'name',
        'role',
        'joint_angles_deg',
        'tool_revision',
        'purpose',
        'minimum_limit_margin_deg',
        'collision_review_sha256',
        'cable_envelope_review_sha256',
    )
    names = set()
    roles = set()
    for index, pose in enumerate(poses):
        label = 'named_poses[{}]'.format(index)
        pose = _exact_keys(pose, pose_keys, label)
        name = _required_string(pose, 'name', issues, label + '.name')
        role = _required_string(pose, 'role', issues, label + '.role')
        target = _required_vector(
            pose, 'joint_angles_deg', 6, issues,
            label + '.joint_angles_deg')
        pose_revision = _required_string(
            pose, 'tool_revision', issues, label + '.tool_revision')
        _required_string(pose, 'purpose', issues, label + '.purpose')
        minimum_margin = _required_number(
            pose, 'minimum_limit_margin_deg', issues,
            label + '.minimum_limit_margin_deg', positive=True)
        if (
                minimum_margin is not None
                and required_margin is not None
                and minimum_margin < required_margin):
            _issue(
                issues,
                '{} declares less than the required named-pose margin'
                .format(label))
        _sha256(
            pose, 'collision_review_sha256', issues,
            label + '.collision_review_sha256')
        _sha256(
            pose, 'cable_envelope_review_sha256', issues,
            label + '.cable_envelope_review_sha256')
        if name in names:
            raise ArmMotionManifestError('named pose names must be unique')
        if name is not None:
            names.add(name)
        if role is not None and role not in REQUIRED_POSE_ROLES:
            raise ArmMotionManifestError(
                '{} has an unsupported role'.format(label))
        if role in roles:
            raise ArmMotionManifestError('named pose roles must be unique')
        if role is not None:
            roles.add(role)
        if (
                tool_revision is not None
                and pose_revision is not None
                and tool_revision != pose_revision):
            _issue(issues, label + ' tool revision does not match tool')
        if target is not None and project_limits is not None:
            margins = []
            for joint, (value, limits) in enumerate(
                    zip(target, project_limits), start=1):
                if not limits[0] <= value <= limits[1]:
                    _issue(
                        issues,
                        '{} joint {} is outside project limits'.format(
                            label, joint))
                    continue
                margins.append(min(value - limits[0], limits[1] - value))
            if (
                    margins
                    and minimum_margin is not None
                    and min(margins) < minimum_margin):
                _issue(
                    issues,
                    '{} does not satisfy its declared limit margin'.format(
                        label))
    for role in REQUIRED_POSE_ROLES:
        if role not in roles:
            _issue(issues, 'required named pose role is missing: ' + role)


def _validate_review(review, issues):
    review = _exact_keys(review, (
        'review_id',
        'reviewer',
        'reviewed_at_utc',
        'approval_sha256',
    ), 'review')
    _required_string(review, 'review_id', issues, 'review.review_id')
    _required_string(review, 'reviewer', issues, 'review.reviewer')
    timestamp = _required_string(
        review, 'reviewed_at_utc', issues, 'review.reviewed_at_utc')
    if timestamp is not None:
        if _UTC_TIMESTAMP.fullmatch(timestamp) is None:
            raise ArmMotionManifestError(
                'review.reviewed_at_utc must use YYYY-MM-DDTHH:MM:SSZ')
        try:
            datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError as exc:
            raise ArmMotionManifestError(
                'review.reviewed_at_utc is not a valid UTC timestamp') \
                from exc
    _sha256(review, 'approval_sha256', issues, 'review.approval_sha256')


def evaluate_manifest(manifest, artifact_root=None):
    """Return a deterministic release report for one manifest object."""
    normalized = _clone_json_value(manifest)
    normalized = _exact_keys(normalized, (
        'schema_version',
        'arm_model',
        'release_binding',
        'source_binding',
        'tool',
        'coordinate_contract',
        'controller_state',
        'motion_profile',
        'real_backend_gate',
        'joint_limits',
        'cartesian_limits',
        'named_poses',
        'review',
        'artifacts',
    ), 'manifest')
    if type(normalized['schema_version']) is not int:
        raise ArmMotionManifestError(
            'schema_version must be a native integer')
    if normalized['schema_version'] != SCHEMA_VERSION:
        raise ArmMotionManifestError(
            'unsupported schema_version: {}'.format(
                normalized['schema_version']))

    issues = []
    resolved_artifact_root = _prepare_artifact_root(artifact_root, issues)
    arm_model = _required_string(
        normalized, 'arm_model', issues, 'arm_model')
    if arm_model is not None and arm_model != EXPECTED_ARM_MODEL:
        _issue(issues, 'arm_model does not match the reviewed platform')
    runtime_release_id = _validate_release_binding(
        normalized['release_binding'], issues)
    _validate_source_binding(normalized['source_binding'], issues)
    _tool_model, tool_revision = _validate_tool(
        normalized['tool'], issues)
    frame_id, endpoint = _validate_coordinate_contract(
        normalized['coordinate_contract'], issues)
    controller_state = _validate_controller_state(
        normalized['controller_state'], issues)
    acceleration_runtime_release_id, physical_limits = _validate_motion_profile(
        normalized['motion_profile'], issues, tool_revision)
    if (
            runtime_release_id is not None
            and acceleration_runtime_release_id is not None
            and runtime_release_id != acceleration_runtime_release_id):
        _issue(
            issues,
            'motion_profile.acceleration_profile_runtime_release_id does not '
            'match release_binding.runtime_release_id')
    _validate_real_backend_gate(normalized['real_backend_gate'], issues)
    project_limits, required_margin = _validate_joint_limits(
        normalized['joint_limits'], issues, controller_state)
    _validate_cartesian_limits(
        normalized['cartesian_limits'], issues, frame_id, endpoint)
    _validate_named_poses(
        normalized['named_poses'], issues, project_limits,
        required_margin, tool_revision)
    _validate_review(normalized['review'], issues)
    artifact_index = _validate_artifact_declarations(
        normalized['artifacts'], issues)
    verified_artifacts = _bind_artifacts(
        normalized, resolved_artifact_root, artifact_index, issues)
    _validate_execution_safety_bindings(
        normalized, artifact_index, verified_artifacts, issues,
        runtime_release_id)
    _validate_acceleration_profile_artifact(
        normalized, verified_artifacts, issues, runtime_release_id,
        physical_limits)
    _validate_runtime_release_artifact(
        normalized, verified_artifacts, issues, runtime_release_id)

    return {
        'schema_version': SCHEMA_VERSION,
        'release_ready': not issues,
        'blocking_issues': issues,
        'normalized_manifest': normalized,
        'verified_artifacts': {
            sha256: artifact_index[sha256]['path']
            for sha256 in sorted(verified_artifacts)
        },
    }


def main(argv=None):
    """Validate one local JSON file and print a machine-readable report."""
    parser = argparse.ArgumentParser(
        description='Evaluate an offline arm motion release manifest.')
    parser.add_argument('manifest')
    parser.add_argument('--artifact-root', required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate_manifest(
            load_manifest(args.manifest), artifact_root=args.artifact_root)
    except (ArmMotionManifestError, OSError) as exc:
        report = {
            'schema_version': SCHEMA_VERSION,
            'release_ready': False,
            'blocking_issues': [str(exc)],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['release_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
