"""Pure-local persistent arm physical-isolation latch contract.

The public API never accepts a caller-selected session identity.  Each create
or open operation obtains a monotonically increasing epoch and random nonce
from a persistent issuance ledger protected by an OS file lock.  The same
non-removable lock file serializes record updates, avoiding owner-check/unlink
races.  Local hashes provide integrity and replay resistance, not authenticity.
"""

import hashlib
import json
import math
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path


SCHEMA_VERSION = 4
CREDENTIAL_SCHEMA_VERSION = 3
LEDGER_SCHEMA_VERSION = 3
PENDING_COMMIT_SCHEMA_VERSION = 2
AUTHENTICITY_LIMIT = 'LOCAL_HASH_CHAIN_ONLY_EXTERNAL_VALIDATOR_REQUIRED'
UPDATE_LOCK_PAYLOAD = b'LIMO_ARM_SAFETY_LATCH_UPDATE_LOCK_V1\n'
MAX_PERSISTENT_FILE_BYTES = 1024 * 1024
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_PROCESS_UPDATE_LOCK = threading.RLock()
RELEASE_BINDING_KEYS = (
    'runtime_release_id',
    'release_manifest_sha256',
    'acceleration_profile_id',
    'acceleration_profile_manifest_sha256',
    'acceleration_profile_runtime_release_id',
    'approved_speed_grades',
    'bounded_call_artifact_sha256',
    'stop_isolation_artifact_sha256',
    'hung_command_stop_report_sha256',
)
_WINDOWS_RESERVED_NAMES = frozenset((
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
))


class ArmSafetyLatchError(RuntimeError):
    """Raised when a persistent latch operation cannot fail closed."""


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArmSafetyLatchError('duplicate JSON key in safety record')
        result[key] = value
    return result


def _reject_nonfinite_constant(unused_value):
    raise ArmSafetyLatchError('non-finite JSON is forbidden')


def _clone_json(value, label='value'):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ArmSafetyLatchError('{} is non-finite'.format(label))
        return value
    if type(value) is list:
        return [_clone_json(item, '{}[{}]'.format(label, index))
                for index, item in enumerate(value)]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ArmSafetyLatchError('{} has a non-string key'.format(label))
            result[key] = _clone_json(item, '{}.{}'.format(label, key))
        return result
    raise ArmSafetyLatchError('{} contains a non-JSON value'.format(label))


def canonical_json_bytes(value):
    return (json.dumps(
        _clone_json(value), ensure_ascii=True, sort_keys=True,
        separators=(',', ':')) + '\n').encode('utf-8')


def _strict_loads(payload):
    if type(payload) is not bytes:
        raise ArmSafetyLatchError('record payload must be bytes')
    try:
        value = json.loads(
            payload.decode('utf-8'), object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant)
    except ArmSafetyLatchError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ArmSafetyLatchError('record must be strict UTF-8 JSON') from exc
    if canonical_json_bytes(value) != payload:
        raise ArmSafetyLatchError('record is not canonical JSON')
    return value


def _exact_string(value, label):
    if type(value) is not str or not value or value != value.strip():
        raise ArmSafetyLatchError('{} must be an exact non-empty string'.format(label))
    return value


def _exact_sha256(value, label):
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ArmSafetyLatchError('{} must be an exact lowercase SHA-256'.format(label))
    return value


def _approved_speed_grades(value, label='approved_speed_grades'):
    if type(value) not in (list, tuple) or not value:
        raise ArmSafetyLatchError(
            '{} must be a non-empty exact array'.format(label))
    grades = []
    for index, grade in enumerate(value):
        if type(grade) is not int or not 1 <= grade <= 100:
            raise ArmSafetyLatchError(
                '{}[{}] must be an exact integer in 1..100'.format(
                    label, index))
        grades.append(grade)
    if grades != sorted(set(grades)):
        raise ArmSafetyLatchError(
            '{} must be unique and strictly increasing'.format(label))
    return grades


def _release_binding(
        runtime_release_id,
        release_manifest_sha256,
        acceleration_profile_id,
        acceleration_profile_manifest_sha256,
        acceleration_profile_runtime_release_id,
        approved_speed_grades,
        bounded_call_artifact_sha256,
        stop_isolation_artifact_sha256,
        hung_command_stop_report_sha256):
    binding = {
        'runtime_release_id': _exact_string(
            runtime_release_id, 'runtime_release_id'),
        'release_manifest_sha256': _exact_sha256(
            release_manifest_sha256, 'release_manifest_sha256'),
        'acceleration_profile_id': _exact_string(
            acceleration_profile_id, 'acceleration_profile_id'),
        'acceleration_profile_manifest_sha256': _exact_sha256(
            acceleration_profile_manifest_sha256,
            'acceleration_profile_manifest_sha256'),
        'acceleration_profile_runtime_release_id': _exact_string(
            acceleration_profile_runtime_release_id,
            'acceleration_profile_runtime_release_id'),
        'approved_speed_grades': _approved_speed_grades(
            approved_speed_grades),
        'bounded_call_artifact_sha256': _exact_sha256(
            bounded_call_artifact_sha256,
            'bounded_call_artifact_sha256'),
        'stop_isolation_artifact_sha256': _exact_sha256(
            stop_isolation_artifact_sha256,
            'stop_isolation_artifact_sha256'),
        'hung_command_stop_report_sha256': _exact_sha256(
            hung_command_stop_report_sha256,
            'hung_command_stop_report_sha256'),
    }
    if (
            binding['acceleration_profile_runtime_release_id']
            != binding['runtime_release_id']):
        raise ArmSafetyLatchError(
            'acceleration profile runtime release ID must exactly match '
            'runtime_release_id')
    if (
            binding['release_manifest_sha256']
            == binding['acceleration_profile_manifest_sha256']):
        raise ArmSafetyLatchError(
            'release and acceleration-profile artifacts must be distinct')
    for name in (
            'bounded_call_artifact_sha256',
            'stop_isolation_artifact_sha256',
            'hung_command_stop_report_sha256'):
        if binding[name] in (
                binding['release_manifest_sha256'],
                binding['acceleration_profile_manifest_sha256']):
            raise ArmSafetyLatchError(
                'execution-safety artifacts must be distinct from release '
                'and acceleration-profile artifacts')
    # The arm release manifest currently permits one reviewed combined JSON
    # artifact to prove bounded calls, STOP isolation and the hung-send probe.
    # The three semantic fields remain explicit even when their hashes match.
    return binding


def _exact_keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ArmSafetyLatchError('{} keys mismatch'.format(label))
    return value


def _prepare_path(value):
    if not isinstance(value, (str, Path)):
        raise ArmSafetyLatchError('latch path must be absolute local storage')
    raw = str(value)
    normalized = raw.replace('\\', '/').casefold()
    if normalized == '/dev' or normalized.startswith('/dev/'):
        raise ArmSafetyLatchError('device paths are forbidden')
    if raw.startswith('\\\\.\\') or raw.startswith('\\\\?\\'):
        raise ArmSafetyLatchError('special filesystem namespaces are forbidden')
    path = Path(value)
    if not path.is_absolute():
        raise ArmSafetyLatchError('latch path must be absolute')
    if not path.name or ':' in path.name or path.name.endswith((' ', '.')):
        raise ArmSafetyLatchError('latch filename is unsafe')
    if path.name.split('.', 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ArmSafetyLatchError('reserved filenames are forbidden')
    absolute_parent = path.parent.absolute()
    current = absolute_parent
    ancestors = []
    while current != current.parent:
        ancestors.append(current)
        current = current.parent
    for ancestor in reversed(ancestors):
        if ancestor.is_symlink():
            raise ArmSafetyLatchError('ancestor symbolic links are forbidden')
    try:
        parent = absolute_parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArmSafetyLatchError('latch parent is unavailable') from exc
    if parent != absolute_parent or not parent.is_dir():
        raise ArmSafetyLatchError('latch parent identity is not stable')
    return parent / path.name


def _record_from_payload(payload):
    payload = _clone_json(payload, 'payload')
    return {
        'schema_version': SCHEMA_VERSION,
        'payload': payload,
        'record_sha256': hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _validate_record(record):
    record = _exact_keys(record, ('schema_version', 'payload', 'record_sha256'), 'record')
    if type(record['schema_version']) is not int or record['schema_version'] != SCHEMA_VERSION:
        raise ArmSafetyLatchError('unsupported safety latch schema version')
    payload = _exact_keys(record['payload'], (
        'store_id', 'generation', 'status',
        'last_issued_session_epoch', 'last_issued_session_nonce',
        'latched_session_epoch', 'latched_session_nonce',
        'minimum_clearing_session_epoch',
        'updated_by_session_epoch', 'updated_by_session_nonce',
        'reason', 'previous_record_sha256',
        'runtime_release_id', 'release_manifest_sha256',
        'acceleration_profile_id',
        'acceleration_profile_manifest_sha256',
        'acceleration_profile_runtime_release_id',
        'approved_speed_grades',
        'bounded_call_artifact_sha256',
        'stop_isolation_artifact_sha256',
        'hung_command_stop_report_sha256',
        'used_clearance_ids_sha256',
        'clearance_id',
        'physical_verification_artifact_sha256', 'approval_artifact_sha256',
        'authenticity_limit'), 'record.payload')
    _exact_string(payload['store_id'], 'store_id')
    binding = _release_binding(
        payload['runtime_release_id'],
        payload['release_manifest_sha256'],
        payload['acceleration_profile_id'],
        payload['acceleration_profile_manifest_sha256'],
        payload['acceleration_profile_runtime_release_id'],
        payload['approved_speed_grades'],
        payload['bounded_call_artifact_sha256'],
        payload['stop_isolation_artifact_sha256'],
        payload['hung_command_stop_report_sha256'],
    )
    if binding['approved_speed_grades'] != payload['approved_speed_grades']:
        raise ArmSafetyLatchError(
            'record approved speed grades are not exact')
    _exact_sha256(
        payload['used_clearance_ids_sha256'],
        'used_clearance_ids_sha256')
    _exact_string(payload['reason'], 'reason')
    _exact_string(payload['updated_by_session_nonce'], 'updated_by_session_nonce')
    if (type(payload['last_issued_session_epoch']) is not int or
            payload['last_issued_session_epoch'] < 1):
        raise ArmSafetyLatchError('last issued session epoch must be positive')
    _exact_string(
        payload['last_issued_session_nonce'], 'last issued session nonce')
    if type(payload['generation']) is not int or payload['generation'] < 0:
        raise ArmSafetyLatchError('generation must be non-negative')
    if type(payload['updated_by_session_epoch']) is not int or payload['updated_by_session_epoch'] < 1:
        raise ArmSafetyLatchError('updated session epoch must be positive')
    if payload['status'] not in ('CLEAR', 'ACTIVE'):
        raise ArmSafetyLatchError('status must be CLEAR or ACTIVE')
    if payload['authenticity_limit'] != AUTHENTICITY_LIMIT:
        raise ArmSafetyLatchError('authenticity limit mismatch')
    previous = payload['previous_record_sha256']
    if previous is not None:
        _exact_sha256(previous, 'previous_record_sha256')
    if payload['generation'] == 0 and previous is not None:
        raise ArmSafetyLatchError(
            'generation zero cannot have a previous record')
    if payload['generation'] > 0 and previous is None:
        raise ArmSafetyLatchError(
            'nonzero generation requires a previous record')
    if payload['status'] == 'ACTIVE':
        if type(payload['latched_session_epoch']) is not int or payload['latched_session_epoch'] < 1:
            raise ArmSafetyLatchError('ACTIVE latch needs a session epoch')
        _exact_string(payload['latched_session_nonce'], 'latched_session_nonce')
        if (type(payload['minimum_clearing_session_epoch']) is not int or
                payload['minimum_clearing_session_epoch']
                <= payload['latched_session_epoch']):
            raise ArmSafetyLatchError('minimum clearing epoch is invalid')
        if any(payload[key] is not None for key in (
                'clearance_id', 'physical_verification_artifact_sha256',
                'approval_artifact_sha256')):
            raise ArmSafetyLatchError('ACTIVE latch cannot contain clearance')
    else:
        if payload['generation'] == 0:
            if any(payload[key] is not None for key in (
                    'latched_session_epoch', 'latched_session_nonce',
                    'minimum_clearing_session_epoch', 'clearance_id',
                    'physical_verification_artifact_sha256',
                    'approval_artifact_sha256')):
                raise ArmSafetyLatchError('initial CLEAR record is invalid')
            if (payload['last_issued_session_epoch'] != 1 or
                    payload['updated_by_session_epoch'] != 1 or
                    payload['last_issued_session_nonce'] !=
                    payload['updated_by_session_nonce']):
                raise ArmSafetyLatchError(
                    'initial CLEAR session anchor is invalid')
        else:
            clearance = (
                payload['clearance_id'],
                payload['physical_verification_artifact_sha256'],
                payload['approval_artifact_sha256'],
            )
            if all(value is None for value in clearance):
                if any(payload[key] is not None for key in (
                        'latched_session_epoch', 'latched_session_nonce',
                        'minimum_clearing_session_epoch')):
                    raise ArmSafetyLatchError(
                        'CLEAR session event cannot discard latch evidence')
            elif any(value is None for value in clearance):
                raise ArmSafetyLatchError(
                    'CLEAR clearance evidence must be complete')
            else:
                if (type(payload['latched_session_epoch']) is not int or
                        payload['latched_session_epoch'] < 1):
                    raise ArmSafetyLatchError(
                        'cleared record needs a latching session epoch')
                _exact_string(
                    payload['latched_session_nonce'],
                    'cleared record latching session nonce')
                if (type(payload['minimum_clearing_session_epoch']) is not int or
                        payload['minimum_clearing_session_epoch'] <=
                        payload['latched_session_epoch'] or
                        payload['updated_by_session_epoch'] <
                        payload['minimum_clearing_session_epoch']):
                    raise ArmSafetyLatchError(
                        'cleared record session boundary is invalid')
                _exact_string(payload['clearance_id'], 'clearance_id')
                for key in (
                        'physical_verification_artifact_sha256',
                        'approval_artifact_sha256'):
                    _exact_sha256(payload[key], key)
    expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if record['record_sha256'] != expected:
        raise ArmSafetyLatchError('safety latch record SHA-256 mismatch')
    return _clone_json(record)


def _ledger_from_payload(payload):
    payload = _clone_json(payload, 'session ledger payload')
    return {
        'schema_version': LEDGER_SCHEMA_VERSION,
        'payload': payload,
        'ledger_sha256': hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _clearance_ids_sha256(clearance_ids):
    return hashlib.sha256(canonical_json_bytes(clearance_ids)).hexdigest()


def _validate_ledger(ledger):
    ledger = _exact_keys(
        ledger, ('schema_version', 'payload', 'ledger_sha256'),
        'session ledger')
    if (type(ledger['schema_version']) is not int or
            ledger['schema_version'] != LEDGER_SCHEMA_VERSION):
        raise ArmSafetyLatchError('session ledger schema mismatch')
    payload = _exact_keys(ledger['payload'], (
        'store_id',
        'runtime_release_id', 'release_manifest_sha256',
        'acceleration_profile_id',
        'acceleration_profile_manifest_sha256',
        'acceleration_profile_runtime_release_id',
        'approved_speed_grades',
        'bounded_call_artifact_sha256',
        'stop_isolation_artifact_sha256',
        'hung_command_stop_report_sha256',
        'last_session_epoch', 'last_session_nonce', 'issued_sessions',
        'used_clearance_ids'), 'session ledger payload')
    _exact_string(payload['store_id'], 'session ledger store_id')
    binding = _release_binding(
        payload['runtime_release_id'],
        payload['release_manifest_sha256'],
        payload['acceleration_profile_id'],
        payload['acceleration_profile_manifest_sha256'],
        payload['acceleration_profile_runtime_release_id'],
        payload['approved_speed_grades'],
        payload['bounded_call_artifact_sha256'],
        payload['stop_isolation_artifact_sha256'],
        payload['hung_command_stop_report_sha256'],
    )
    if binding['approved_speed_grades'] != payload['approved_speed_grades']:
        raise ArmSafetyLatchError(
            'session ledger approved speed grades are not exact')
    sessions = payload['issued_sessions']
    if type(sessions) is not list or not sessions:
        raise ArmSafetyLatchError('session ledger history must be non-empty')
    nonces = set()
    for expected_epoch, session in enumerate(sessions, 1):
        session = _exact_keys(
            session, ('epoch', 'nonce'), 'session ledger history entry')
        if type(session['epoch']) is not int or session['epoch'] != expected_epoch:
            raise ArmSafetyLatchError(
                'session ledger epoch sequence is not contiguous')
        nonce = _exact_string(session['nonce'], 'session ledger nonce')
        if nonce in nonces:
            raise ArmSafetyLatchError('session ledger nonce reuse is forbidden')
        nonces.add(nonce)
    latest = sessions[-1]
    if (type(payload['last_session_epoch']) is not int or
            payload['last_session_epoch'] != latest['epoch'] or
            type(payload['last_session_nonce']) is not str or
            payload['last_session_nonce'] != latest['nonce']):
        raise ArmSafetyLatchError('session ledger latest-session fields mismatch')
    clearance_ids = payload['used_clearance_ids']
    if type(clearance_ids) is not list:
        raise ArmSafetyLatchError('used clearance IDs must be a list')
    normalized_ids = []
    for clearance_id in clearance_ids:
        normalized_ids.append(_exact_string(
            clearance_id, 'used clearance ID'))
    if normalized_ids != sorted(set(normalized_ids)):
        raise ArmSafetyLatchError(
            'used clearance IDs must be unique and canonically sorted')
    expected_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if (type(ledger['ledger_sha256']) is not str or
            ledger['ledger_sha256'] != expected_hash):
        raise ArmSafetyLatchError('session ledger SHA-256 mismatch')
    return _clone_json(ledger)


def _reject_link_or_reparse(metadata, label):
    if stat.S_ISLNK(metadata.st_mode):
        raise ArmSafetyLatchError('{} symbolic links are forbidden'.format(label))
    if os.name == 'nt':
        attributes = getattr(metadata, 'st_file_attributes', None)
        reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', None)
        if type(attributes) is not int or type(reparse_flag) is not int:
            raise ArmSafetyLatchError(
                'Windows reparse-point inspection is unavailable; fail closed')
        if attributes & reparse_flag:
            raise ArmSafetyLatchError(
                '{} reparse points are forbidden'.format(label))


def _stable_identity(metadata, label):
    device = getattr(metadata, 'st_dev', None)
    inode = getattr(metadata, 'st_ino', None)
    if (type(device) is not int or type(inode) is not int or inode <= 0):
        raise ArmSafetyLatchError(
            '{} stable file identity is unavailable; fail closed'.format(label))
    return device, inode


def _validate_regular_metadata(metadata, label):
    _reject_link_or_reparse(metadata, label)
    if not stat.S_ISREG(metadata.st_mode):
        raise ArmSafetyLatchError('{} must be an ordinary file'.format(label))
    links = getattr(metadata, 'st_nlink', None)
    if type(links) is not int or links != 1:
        raise ArmSafetyLatchError(
            '{} must have exactly one filesystem link'.format(label))
    return _stable_identity(metadata, label)


def _lstat_regular(path, label):
    try:
        metadata = os.lstat(str(path))
    except OSError as exc:
        raise ArmSafetyLatchError('{} is unavailable'.format(label)) from exc
    _validate_regular_metadata(metadata, label)
    return metadata


def _path_entry_exists(path, label):
    try:
        metadata = os.lstat(str(path))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ArmSafetyLatchError('{} cannot be inspected'.format(label)) from exc
    _validate_regular_metadata(metadata, label)
    return True


def _validate_opened_path(descriptor, path, label):
    opened = os.fstat(descriptor)
    opened_identity = _validate_regular_metadata(opened, label)
    path_metadata = _lstat_regular(path, label)
    if _stable_identity(path_metadata, label) != opened_identity:
        raise ArmSafetyLatchError('{} path/inode identity changed'.format(label))
    return opened


def _read_descriptor(descriptor, maximum_size, label):
    os.lseek(descriptor, 0, os.SEEK_SET)
    blocks = []
    total = 0
    while True:
        block = os.read(descriptor, 65536)
        if not block:
            break
        total += len(block)
        if total > maximum_size:
            raise ArmSafetyLatchError('{} exceeds the size limit'.format(label))
        blocks.append(block)
    return b''.join(blocks)


def _read_regular_file_once(
        path, label, maximum_size=MAX_PERSISTENT_FILE_BYTES):
    _lstat_regular(path, label)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(str(path), flags)
        _validate_opened_path(descriptor, path, label)
        payload = _read_descriptor(descriptor, maximum_size, label)
        _validate_opened_path(descriptor, path, label)
        return payload
    except ArmSafetyLatchError:
        raise
    except OSError as exc:
        raise ArmSafetyLatchError('{} read failed'.format(label)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_exclusive(path, payload, label):
    if (type(payload) is not bytes or not payload or
            len(payload) > MAX_PERSISTENT_FILE_BYTES):
        raise ArmSafetyLatchError(
            '{} payload size is invalid'.format(label))
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
             getattr(os, 'O_BINARY', 0))
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(str(path), flags, 0o600)
        _validate_opened_path(descriptor, path, label)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        _validate_opened_path(descriptor, path, label)
    except FileExistsError as exc:
        raise ArmSafetyLatchError('{} already exists'.format(label)) from exc
    except ArmSafetyLatchError:
        raise
    except OSError as exc:
        raise ArmSafetyLatchError('{} exclusive write failed'.format(label)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fsync_directory(path):
    if os.name != 'posix':
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lock_descriptor(descriptor):
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        raise ArmSafetyLatchError(
            'persistent update lock acquisition failed') from exc


def _unlock_descriptor(descriptor):
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise ArmSafetyLatchError(
            'persistent update lock release failed') from exc


@contextmanager
def _locked_update_file(path):
    with _PROCESS_UPDATE_LOCK:
        _lstat_regular(path, 'persistent update lock')
        flags = os.O_RDWR | getattr(os, 'O_BINARY', 0)
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        descriptor = None
        acquired = False
        try:
            descriptor = os.open(str(path), flags)
            _validate_opened_path(
                descriptor, path, 'persistent update lock')
            if _read_descriptor(
                    descriptor, len(UPDATE_LOCK_PAYLOAD) + 1,
                    'persistent update lock') != UPDATE_LOCK_PAYLOAD:
                raise ArmSafetyLatchError(
                    'persistent update lock marker is invalid')
            _lock_descriptor(descriptor)
            acquired = True
            _validate_opened_path(
                descriptor, path, 'persistent update lock')
            if _read_descriptor(
                    descriptor, len(UPDATE_LOCK_PAYLOAD) + 1,
                    'persistent update lock') != UPDATE_LOCK_PAYLOAD:
                raise ArmSafetyLatchError(
                    'persistent update lock marker changed')
            try:
                yield
            finally:
                _validate_opened_path(
                    descriptor, path, 'persistent update lock')
                if _read_descriptor(
                        descriptor, len(UPDATE_LOCK_PAYLOAD) + 1,
                        'persistent update lock') != UPDATE_LOCK_PAYLOAD:
                    raise ArmSafetyLatchError(
                        'persistent update lock marker changed during operation')
        except ArmSafetyLatchError:
            raise
        except OSError as exc:
            raise ArmSafetyLatchError(
                'persistent update lock operation failed') from exc
        finally:
            try:
                if acquired:
                    _unlock_descriptor(descriptor)
            finally:
                if descriptor is not None:
                    os.close(descriptor)


def _atomic_replace(path, payload, token, label):
    if not _path_entry_exists(path, label):
        raise ArmSafetyLatchError('{} disappeared before update'.format(label))
    temporary = path.with_name('{}.tmp.{}'.format(path.name, token))
    _write_exclusive(temporary, payload, '{} temporary'.format(label))
    try:
        os.replace(str(temporary), str(path))
        if _read_regular_file_once(path, label) != payload:
            raise ArmSafetyLatchError(
                '{} publication verification failed'.format(label))
        _fsync_directory(path.parent)
    except ArmSafetyLatchError:
        raise
    except OSError as exc:
        raise ArmSafetyLatchError('{} atomic update failed'.format(label)) from exc
    finally:
        try:
            os.unlink(str(temporary))
        except FileNotFoundError:
            pass
        except OSError:
            pass


class PersistentArmSafetyLatch:
    """Canonical latch store with ledger-issued process session identity."""

    def __init__(
            self, path, runtime_release_id, release_manifest_sha256,
            acceleration_profile_id,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
            approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256):
        self._path = _prepare_path(path)
        self._binding = _release_binding(
            runtime_release_id,
            release_manifest_sha256,
            acceleration_profile_id,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
            approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256,
        )
        self._runtime_release_id = self._binding['runtime_release_id']
        self._release_manifest_sha256 = self._binding[
            'release_manifest_sha256']
        self._ledger_path = self._path.with_name(
            self._path.name + '.sessions')
        self._update_lock_path = self._path.with_name(
            self._path.name + '.update-lock')
        self._pending_commit_path = self._path.with_name(
            self._path.name + '.commit-pending')
        self._thread_lock = threading.RLock()
        self.session_epoch = None
        self.session_nonce = None

    def _bind_session(self, epoch, nonce):
        if self.session_epoch is not None or self.session_nonce is not None:
            raise ArmSafetyLatchError('process session is already bound')
        self.session_epoch = epoch
        self.session_nonce = nonce

    def _assert_no_pending_commit_unlocked(self):
        if _path_entry_exists(
                self._pending_commit_path, 'pending commit marker'):
            raise ArmSafetyLatchError(
                'persistent commit outcome is uncertain; fail closed and '
                'require audited recovery')

    def _begin_pending_commit_unlocked(self, operation):
        operation = _exact_string(operation, 'pending commit operation')
        marker = {
            'schema_version': PENDING_COMMIT_SCHEMA_VERSION,
            'operation': operation,
            'token': uuid.uuid4().hex,
        }
        marker.update(_clone_json(self._binding, 'pending commit binding'))
        marker_bytes = canonical_json_bytes(marker)
        _write_exclusive(
            self._pending_commit_path, marker_bytes,
            'pending commit marker')
        _fsync_directory(self._path.parent)
        return marker_bytes

    def _finish_pending_commit(self, expected_marker_bytes):
        actual = _read_regular_file_once(
            self._pending_commit_path, 'pending commit marker')
        if actual != expected_marker_bytes:
            raise ArmSafetyLatchError(
                'pending commit marker changed; commit remains uncertain')
        try:
            os.unlink(str(self._pending_commit_path))
        except OSError as exc:
            raise ArmSafetyLatchError(
                'committed state cannot clear its pending marker') from exc
        try:
            _fsync_directory(self._path.parent)
        except OSError:
            # Marker removal is the runtime-visible commit point.  Power-loss
            # durability after this point remains an explicitly blocked target
            # property rather than being misreported as an uncommitted update.
            pass

    @staticmethod
    def _latest_session(ledger):
        payload = ledger['payload']
        return payload['last_session_epoch'], payload['last_session_nonce']

    @staticmethod
    def _session_history(ledger):
        return {
            session['epoch']: session['nonce']
            for session in ledger['payload']['issued_sessions']
        }

    def _read_bound_record_unlocked(self):
        record = _validate_record(_strict_loads(_read_regular_file_once(
            self._path, 'persistent latch record')))
        payload = record['payload']
        for key, expected in self._binding.items():
            if payload[key] != expected or type(payload[key]) is not type(
                    expected):
                raise ArmSafetyLatchError(
                    'persistent latch release/profile/execution binding '
                    'mismatch')
        return record

    def _read_bound_ledger_unlocked(self, record):
        try:
            ledger = _validate_ledger(_strict_loads(_read_regular_file_once(
                self._ledger_path, 'persistent session ledger')))
        except ArmSafetyLatchError as exc:
            raise ArmSafetyLatchError(
                'persistent session ledger is invalid; fail closed: {}'.format(
                    exc)) from exc
        payload = ledger['payload']
        record_payload = record['payload']
        if payload['store_id'] != record_payload['store_id']:
            raise ArmSafetyLatchError(
                'session ledger store/release binding mismatch')
        for key, expected in self._binding.items():
            if (
                    payload[key] != expected
                    or type(payload[key]) is not type(expected)
                    or record_payload[key] != expected
                    or type(record_payload[key]) is not type(expected)):
                raise ArmSafetyLatchError(
                    'session ledger store/release/profile/execution binding '
                    'mismatch')
        history = self._session_history(ledger)
        record_pairs = (
            ('record session anchor',
             record_payload['last_issued_session_epoch'],
             record_payload['last_issued_session_nonce']),
            ('record updater',
             record_payload['updated_by_session_epoch'],
             record_payload['updated_by_session_nonce']),
        )
        for label, epoch, nonce in record_pairs:
            if history.get(epoch) != nonce:
                raise ArmSafetyLatchError(
                    '{} is absent from the session ledger'.format(label))
        if record_payload['latched_session_epoch'] is not None:
            if history.get(record_payload['latched_session_epoch']) != \
                    record_payload['latched_session_nonce']:
                raise ArmSafetyLatchError(
                    'latching session is absent from the session ledger')
        if self._latest_session(ledger) != (
                record_payload['last_issued_session_epoch'],
                record_payload['last_issued_session_nonce']):
            raise ArmSafetyLatchError(
                'record/session-ledger anchor mismatch; fail closed')
        if record_payload['used_clearance_ids_sha256'] != \
                _clearance_ids_sha256(payload['used_clearance_ids']):
            raise ArmSafetyLatchError(
                'record/session-ledger clearance registry mismatch; '
                'fail closed')
        return ledger

    def _load_state_unlocked(self, require_bound_session=True):
        record = self._read_bound_record_unlocked()
        ledger = self._read_bound_ledger_unlocked(record)
        if require_bound_session:
            if self.session_epoch is None or self.session_nonce is None:
                raise ArmSafetyLatchError('process session is not bound')
            if self._session_history(ledger).get(self.session_epoch) != \
                    self.session_nonce:
                raise ArmSafetyLatchError(
                    'bound process session is absent or forged')
        return record, ledger

    def _require_latest_session(self, ledger):
        if self._latest_session(ledger) != (
                self.session_epoch, self.session_nonce):
            raise ArmSafetyLatchError(
                'only the latest issued process session may clear the latch')

    def _write_ledger_unlocked(self, ledger, token):
        normalized = _validate_ledger(ledger)
        _atomic_replace(
            self._ledger_path, canonical_json_bytes(normalized), token,
            'persistent session ledger')
        return normalized

    @classmethod
    def create(
            cls, path, runtime_release_id, release_manifest_sha256,
            acceleration_profile_id,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
            approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256,
            store_id_factory=None):
        store = cls(
            path, runtime_release_id, release_manifest_sha256,
            acceleration_profile_id,
            acceleration_profile_manifest_sha256,
            acceleration_profile_runtime_release_id,
            approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256)
        factory = store_id_factory
        with _PROCESS_UPDATE_LOCK:
            record_exists = _path_entry_exists(
                store._path, 'persistent latch record')
            ledger_exists = _path_entry_exists(
                store._ledger_path, 'persistent session ledger')
            pending_exists = _path_entry_exists(
                store._pending_commit_path, 'pending commit marker')
            lock_exists = _path_entry_exists(
                store._update_lock_path, 'persistent update lock')
            if (record_exists or ledger_exists or pending_exists) and \
                    not lock_exists:
                raise ArmSafetyLatchError(
                    'safety latch store already exists but its update lock is missing')
            if not lock_exists:
                _write_exclusive(
                    store._update_lock_path, UPDATE_LOCK_PAYLOAD,
                    'persistent update lock')
                _fsync_directory(store._path.parent)
            with _locked_update_file(store._update_lock_path):
                store._assert_no_pending_commit_unlocked()
                if _path_entry_exists(
                        store._path, 'persistent latch record'):
                    raise ArmSafetyLatchError(
                        'safety latch file already exists')
                if _path_entry_exists(
                        store._ledger_path, 'persistent session ledger'):
                    raise ArmSafetyLatchError(
                        'orphaned session ledger forbids store re-creation')
                if factory is None:
                    raw_store_id = uuid.uuid4().hex
                else:
                    if not callable(factory):
                        raise ArmSafetyLatchError(
                            'store_id_factory must be callable')
                    raw_store_id = factory()
                store_id = _exact_string(
                    raw_store_id, 'store_id_factory result')
                nonce = uuid.uuid4().hex
                ledger_payload = {
                    'store_id': store_id,
                    'last_session_epoch': 1,
                    'last_session_nonce': nonce,
                    'issued_sessions': [{'epoch': 1, 'nonce': nonce}],
                    'used_clearance_ids': [],
                }
                ledger_payload.update(_clone_json(
                    store._binding, 'initial ledger binding'))
                ledger = _validate_ledger(_ledger_from_payload(ledger_payload))
                payload = {
                    'store_id': store_id,
                    'generation': 0,
                    'status': 'CLEAR',
                    'last_issued_session_epoch': 1,
                    'last_issued_session_nonce': nonce,
                    'latched_session_epoch': None,
                    'latched_session_nonce': None,
                    'minimum_clearing_session_epoch': None,
                    'updated_by_session_epoch': 1,
                    'updated_by_session_nonce': nonce,
                    'reason': 'persistent safety latch store initialized',
                    'previous_record_sha256': None,
                    'used_clearance_ids_sha256':
                        _clearance_ids_sha256([]),
                    'clearance_id': None,
                    'physical_verification_artifact_sha256': None,
                    'approval_artifact_sha256': None,
                    'authenticity_limit': AUTHENTICITY_LIMIT,
                }
                payload.update(_clone_json(
                    store._binding, 'initial record binding'))
                record = _validate_record(_record_from_payload(payload))
                ledger_bytes = canonical_json_bytes(ledger)
                record_bytes = canonical_json_bytes(record)
                if (len(ledger_bytes) > MAX_PERSISTENT_FILE_BYTES or
                        len(record_bytes) > MAX_PERSISTENT_FILE_BYTES):
                    raise ArmSafetyLatchError(
                        'initial safety latch files exceed the size limit')
                pending = store._begin_pending_commit_unlocked('CREATE')
                _write_exclusive(
                    store._ledger_path, ledger_bytes,
                    'persistent session ledger')
                _write_exclusive(
                    store._path, record_bytes,
                    'persistent latch record')
                _fsync_directory(store._path.parent)
                store._bind_session(1, nonce)
            store._finish_pending_commit(pending)
        return store

    @classmethod
    def open(
            cls, path, expected_runtime_release_id,
            expected_release_manifest_sha256,
            expected_acceleration_profile_id,
            expected_acceleration_profile_manifest_sha256,
            expected_acceleration_profile_runtime_release_id,
            expected_approved_speed_grades,
            expected_bounded_call_artifact_sha256,
            expected_stop_isolation_artifact_sha256,
            expected_hung_command_stop_report_sha256):
        store = cls(
            path, expected_runtime_release_id,
            expected_release_manifest_sha256,
            expected_acceleration_profile_id,
            expected_acceleration_profile_manifest_sha256,
            expected_acceleration_profile_runtime_release_id,
            expected_approved_speed_grades,
            expected_bounded_call_artifact_sha256,
            expected_stop_isolation_artifact_sha256,
            expected_hung_command_stop_report_sha256)
        nonce = uuid.uuid4().hex
        with _locked_update_file(store._update_lock_path):
            store._assert_no_pending_commit_unlocked()
            current, ledger = store._load_state_unlocked(
                require_bound_session=False)
            ledger_payload = _clone_json(ledger['payload'])
            epoch = ledger_payload['last_session_epoch'] + 1
            ledger_payload['last_session_epoch'] = epoch
            ledger_payload['last_session_nonce'] = nonce
            ledger_payload['issued_sessions'].append({
                'epoch': epoch, 'nonce': nonce})
            updated_ledger = _validate_ledger(
                _ledger_from_payload(ledger_payload))
            payload = _clone_json(current['payload'])
            payload.update({
                'generation': payload['generation'] + 1,
                'last_issued_session_epoch': epoch,
                'last_issued_session_nonce': nonce,
                'updated_by_session_epoch': epoch,
                'updated_by_session_nonce': nonce,
                'previous_record_sha256': current['record_sha256'],
            })
            updated_record = _validate_record(_record_from_payload(payload))
            pending = store._begin_pending_commit_unlocked('OPEN_SESSION')
            store._write_ledger_unlocked(
                updated_ledger, uuid.uuid4().hex)
            _atomic_replace(
                store._path, canonical_json_bytes(updated_record),
                uuid.uuid4().hex, 'persistent latch record')
            store._read_bound_ledger_unlocked(updated_record)
            store._bind_session(
                updated_ledger['payload']['last_session_epoch'],
                updated_ledger['payload']['last_session_nonce'])
        store._finish_pending_commit(pending)
        return store

    @property
    def path(self):
        return self._path

    def snapshot(self):
        with self._thread_lock, _locked_update_file(self._update_lock_path):
            self._assert_no_pending_commit_unlocked()
            record, unused_ledger = self._load_state_unlocked()
            return record

    @property
    def active(self):
        return self.snapshot()['payload']['status'] == 'ACTIVE'

    def latch(self, reason):
        reason = _exact_string(reason, 'latch reason')
        with self._thread_lock, _locked_update_file(self._update_lock_path):
            self._assert_no_pending_commit_unlocked()
            current, ledger = self._load_state_unlocked()
            latest_session_epoch, latest_session_nonce = \
                self._latest_session(ledger)
            payload = _clone_json(current['payload'])
            payload.update({
                'generation': payload['generation'] + 1,
                'status': 'ACTIVE',
                'last_issued_session_epoch': latest_session_epoch,
                'last_issued_session_nonce': latest_session_nonce,
                'latched_session_epoch': self.session_epoch,
                'latched_session_nonce': self.session_nonce,
                'minimum_clearing_session_epoch': latest_session_epoch + 1,
                'updated_by_session_epoch': self.session_epoch,
                'updated_by_session_nonce': self.session_nonce,
                'reason': reason,
                'previous_record_sha256': current['record_sha256'],
                'clearance_id': None,
                'physical_verification_artifact_sha256': None,
                'approval_artifact_sha256': None,
            })
            record = _validate_record(_record_from_payload(payload))
            pending = self._begin_pending_commit_unlocked('LATCH')
            _atomic_replace(
                self._path, canonical_json_bytes(record),
                uuid.uuid4().hex, 'persistent latch record')
        self._finish_pending_commit(pending)
        return record

    def build_clearance_credential(
            self, clearance_id,
            physical_verification_artifact_sha256,
            approval_artifact_sha256):
        clearance_id = _exact_string(clearance_id, 'clearance_id')
        with self._thread_lock, _locked_update_file(self._update_lock_path):
            self._assert_no_pending_commit_unlocked()
            current, ledger = self._load_state_unlocked()
            payload = current['payload']
            if payload['status'] != 'ACTIVE':
                raise ArmSafetyLatchError(
                    'no active safety latch can be cleared')
            if self.session_epoch < payload['minimum_clearing_session_epoch']:
                raise ArmSafetyLatchError(
                    'a session issued before the latch cannot clear it')
            self._require_latest_session(ledger)
            if clearance_id in ledger['payload']['used_clearance_ids']:
                raise ArmSafetyLatchError(
                    'clearance ID was already consumed; replay is forbidden')
            return {
                'schema_version': CREDENTIAL_SCHEMA_VERSION,
                'store_id': payload['store_id'],
                'expected_generation': payload['generation'],
                'expected_record_sha256': current['record_sha256'],
                'latched_session_epoch': payload['latched_session_epoch'],
                'latched_session_nonce': payload['latched_session_nonce'],
                'minimum_clearing_session_epoch': payload[
                    'minimum_clearing_session_epoch'],
                'clearing_session_epoch': self.session_epoch,
                'clearing_session_nonce': self.session_nonce,
                'runtime_release_id': payload['runtime_release_id'],
                'release_manifest_sha256': payload[
                    'release_manifest_sha256'],
                'acceleration_profile_id': payload[
                    'acceleration_profile_id'],
                'acceleration_profile_manifest_sha256': payload[
                    'acceleration_profile_manifest_sha256'],
                'acceleration_profile_runtime_release_id': payload[
                    'acceleration_profile_runtime_release_id'],
                'approved_speed_grades': _clone_json(
                    payload['approved_speed_grades']),
                'bounded_call_artifact_sha256': payload[
                    'bounded_call_artifact_sha256'],
                'stop_isolation_artifact_sha256': payload[
                    'stop_isolation_artifact_sha256'],
                'hung_command_stop_report_sha256': payload[
                    'hung_command_stop_report_sha256'],
                'clearance_id': clearance_id,
                'physical_verification_artifact_sha256': _exact_sha256(
                    physical_verification_artifact_sha256,
                    'physical verification hash'),
                'approval_artifact_sha256': _exact_sha256(
                    approval_artifact_sha256, 'approval hash'),
                'authenticity_limit': AUTHENTICITY_LIMIT,
            }

    def clear(self, credential, approval_validator=None):
        with self._thread_lock, _locked_update_file(self._update_lock_path):
            self._assert_no_pending_commit_unlocked()
            current, ledger = self._load_state_unlocked()
            self._require_latest_session(ledger)
            normalized = self._validate_clearance_credential(
                credential, current)
            if normalized['clearance_id'] in \
                    ledger['payload']['used_clearance_ids']:
                raise ArmSafetyLatchError(
                    'clearance ID was already consumed; replay is forbidden')
        if approval_validator is None:
            raise ArmSafetyLatchError(
                'external approval validator is required')
        try:
            accepted = approval_validator(
                _clone_json(normalized), _clone_json(current))
        except Exception as exc:
            raise ArmSafetyLatchError(
                'external clearance validation failed') from exc
        if accepted is not True:
            raise ArmSafetyLatchError(
                'external clearance validation did not return exact True')
        with self._thread_lock, _locked_update_file(
                self._update_lock_path):
            self._assert_no_pending_commit_unlocked()
            latest, ledger = self._load_state_unlocked()
            self._require_latest_session(ledger)
            if (latest['record_sha256'] !=
                    normalized['expected_record_sha256'] or
                    latest['payload']['generation'] !=
                    normalized['expected_generation']):
                raise ArmSafetyLatchError(
                    'clearance credential is stale after validation')
            self._validate_clearance_credential(normalized, latest)
            used_ids = ledger['payload']['used_clearance_ids']
            if normalized['clearance_id'] in used_ids:
                raise ArmSafetyLatchError(
                    'clearance ID was already consumed; replay is forbidden')
            ledger_payload = _clone_json(ledger['payload'])
            ledger_payload['used_clearance_ids'] = sorted(
                used_ids + [normalized['clearance_id']])
            updated_ledger = _validate_ledger(
                _ledger_from_payload(ledger_payload))
            payload = _clone_json(latest['payload'])
            payload.update({
                'generation': payload['generation'] + 1,
                'status': 'CLEAR',
                'updated_by_session_epoch': self.session_epoch,
                'updated_by_session_nonce': self.session_nonce,
                'reason': 'externally validated physical safety clearance',
                'previous_record_sha256': latest['record_sha256'],
                'used_clearance_ids_sha256': _clearance_ids_sha256(
                    ledger_payload['used_clearance_ids']),
                'clearance_id': normalized['clearance_id'],
                'physical_verification_artifact_sha256': normalized[
                    'physical_verification_artifact_sha256'],
                'approval_artifact_sha256': normalized[
                    'approval_artifact_sha256'],
            })
            record = _validate_record(_record_from_payload(payload))
            pending = self._begin_pending_commit_unlocked('CLEAR')
            self._write_ledger_unlocked(
                updated_ledger, uuid.uuid4().hex)
            _atomic_replace(
                self._path, canonical_json_bytes(record),
                uuid.uuid4().hex, 'persistent latch record')
        self._finish_pending_commit(pending)
        return record

    def _validate_clearance_credential(self, credential, current):
        credential = _clone_json(credential, 'credential')
        credential = _exact_keys(credential, (
            'schema_version', 'store_id', 'expected_generation',
            'expected_record_sha256', 'latched_session_epoch',
            'latched_session_nonce', 'minimum_clearing_session_epoch',
            'clearing_session_epoch', 'clearing_session_nonce',
            'runtime_release_id', 'release_manifest_sha256',
            'acceleration_profile_id',
            'acceleration_profile_manifest_sha256',
            'acceleration_profile_runtime_release_id',
            'approved_speed_grades',
            'bounded_call_artifact_sha256',
            'stop_isolation_artifact_sha256',
            'hung_command_stop_report_sha256',
            'clearance_id',
            'physical_verification_artifact_sha256',
            'approval_artifact_sha256', 'authenticity_limit'), 'credential')
        if (type(credential['schema_version']) is not int or
                credential['schema_version'] != CREDENTIAL_SCHEMA_VERSION):
            raise ArmSafetyLatchError('credential schema mismatch')
        payload = current['payload']
        if payload['status'] != 'ACTIVE':
            raise ArmSafetyLatchError(
                'no active safety latch can be cleared')
        expected = {
            'store_id': payload['store_id'],
            'expected_generation': payload['generation'],
            'expected_record_sha256': current['record_sha256'],
            'latched_session_epoch': payload['latched_session_epoch'],
            'latched_session_nonce': payload['latched_session_nonce'],
            'minimum_clearing_session_epoch':
                payload['minimum_clearing_session_epoch'],
            'clearing_session_epoch': self.session_epoch,
            'clearing_session_nonce': self.session_nonce,
            'authenticity_limit': AUTHENTICITY_LIMIT,
        }
        expected.update(_clone_json(
            self._binding, 'expected credential binding'))
        for key, value in expected.items():
            if (credential.get(key) != value or
                    type(credential.get(key)) is not type(value)):
                raise ArmSafetyLatchError(
                    'credential {} does not match active record'.format(key))
        if self.session_epoch < payload['minimum_clearing_session_epoch']:
            raise ArmSafetyLatchError(
                'a session issued before the latch cannot clear it')
        _exact_string(credential['clearance_id'], 'clearance_id')
        _exact_sha256(
            credential['physical_verification_artifact_sha256'],
            'physical hash')
        _exact_sha256(
            credential['approval_artifact_sha256'], 'approval hash')
        return credential
