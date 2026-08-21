"""Append-only local persistent safety latch for an unreleased gripper.

This filesystem-only module never imports ROS or a vendor runtime. It is a
machine-readable fail-closed contract, not a hardware release mechanism. A
local SHA-256 chain provides integrity and replay checks but is not a
signature, so clearance always requires an injected external validator.
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

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


SCHEMA_VERSION = 2
CREDENTIAL_SCHEMA_VERSION = 2
AUTHENTICITY_LIMIT = (
    'LOCAL_APPEND_ONLY_HASH_CHAIN_EXTERNAL_VALIDATOR_REQUIRED')
MAX_RECORD_BYTES = 1024 * 1024
WRITER_LOCK_NAME = '.writer-lock'
WRITER_LOCK_PAYLOAD = b'GRIPPER_SAFETY_LATCH_WRITER_LOCK_V1\n'
_PROCESS_WRITER_LOCK = threading.RLock()
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_GENERATION_NAME = re.compile(r'^generation-([0-9]{20})$')
_TRANSACTION_PREFIX = '.transaction-'
_TOKEN = re.compile(r'^[A-Za-z0-9._:-]{8,160}$')
_WINDOWS_REPARSE_POINT = 0x400
_WINDOWS_RESERVED_NAMES = frozenset((
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
    'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5',
    'LPT6', 'LPT7', 'LPT8', 'LPT9',
))


class GripperSafetyLatchError(RuntimeError):
    """Raised when a persistent latch operation cannot remain fail-closed."""


def _reject_duplicate_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GripperSafetyLatchError(
                'duplicate JSON key in gripper safety latch record')
        value[key] = item
    return value


def _reject_nonfinite(unused_value):
    raise GripperSafetyLatchError(
        'non-finite JSON is forbidden in gripper safety latch records')


def _clone_json(value, label='value'):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise GripperSafetyLatchError(
                '{} contains a non-finite number'.format(label))
        return value
    if type(value) is list:
        return [
            _clone_json(item, '{}[{}]'.format(label, index))
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise GripperSafetyLatchError(
                    '{} contains a non-string key'.format(label))
            result[key] = _clone_json(
                item, '{}.{}'.format(label, key))
        return result
    raise GripperSafetyLatchError(
        '{} contains a non-JSON value'.format(label))


def canonical_json_bytes(value):
    """Return the sole accepted UTF-8 representation."""
    return (
        json.dumps(
            _clone_json(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(',', ':'),
        ) + '\n'
    ).encode('utf-8')


def _strict_loads(payload):
    if type(payload) is not bytes:
        raise GripperSafetyLatchError('record payload must be bytes')
    try:
        value = json.loads(
            payload.decode('utf-8'),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except GripperSafetyLatchError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise GripperSafetyLatchError(
            'record must be strict UTF-8 JSON') from exc
    if canonical_json_bytes(value) != payload:
        raise GripperSafetyLatchError('record is not canonical JSON')
    return value


def _exact_keys(value, keys, label):
    if type(value) is not dict:
        raise GripperSafetyLatchError(
            '{} must be a JSON object'.format(label))
    actual = set(value)
    expected = set(keys)
    if actual != expected:
        raise GripperSafetyLatchError(
            '{} keys mismatch; missing={}, unknown={}'.format(
                label,
                sorted(expected - actual),
                sorted(actual - expected),
            ))
    return value


def _exact_string(value, label):
    if (
            type(value) is not str
            or not value
            or value != value.strip()
            or len(value) > 256):
        raise GripperSafetyLatchError(
            '{} must be an exact non-empty string'.format(label))
    return value


def _exact_token(value, label):
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise GripperSafetyLatchError(
            '{} must be an exact safe token'.format(label))
    return value


def _exact_sha256(value, label):
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise GripperSafetyLatchError(
            '{} must be an exact lowercase SHA-256'.format(label))
    return value


def _approved_speed_grades(value, label='approved_speed_grades'):
    if type(value) is not list or not value:
        raise GripperSafetyLatchError(
            '{} must be a non-empty array'.format(label))
    result = []
    for index, grade in enumerate(value):
        if type(grade) is not int or grade < 1 or grade > 100:
            raise GripperSafetyLatchError(
                '{}[{}] must be an integer in 1..100'.format(label, index))
        result.append(grade)
    if result != sorted(set(result)):
        raise GripperSafetyLatchError(
            '{} must be unique and increasing'.format(label))
    return result


def _release_binding(
        runtime_release_id,
        release_manifest_sha256,
        motion_profile_id,
        motion_profile_manifest_sha256,
        motion_profile_runtime_release_id,
        approved_speed_grades,
        bounded_call_artifact_sha256,
        stop_isolation_artifact_sha256,
        hung_command_stop_report_sha256):
    binding = {
        'runtime_release_id': _exact_string(
            runtime_release_id, 'runtime_release_id'),
        'release_manifest_sha256': _exact_sha256(
            release_manifest_sha256, 'release_manifest_sha256'),
        'motion_profile_id': _exact_string(
            motion_profile_id, 'motion_profile_id'),
        'motion_profile_manifest_sha256': _exact_sha256(
            motion_profile_manifest_sha256,
            'motion_profile_manifest_sha256'),
        'motion_profile_runtime_release_id': _exact_string(
            motion_profile_runtime_release_id,
            'motion_profile_runtime_release_id'),
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
            binding['motion_profile_runtime_release_id']
            != binding['runtime_release_id']):
        raise GripperSafetyLatchError(
            'motion profile runtime release ID must exactly match '
            'runtime_release_id')
    if (
            binding['release_manifest_sha256']
            == binding['motion_profile_manifest_sha256']):
        raise GripperSafetyLatchError(
            'release and motion-profile artifacts must be distinct')
    artifact_hashes = (
        binding['release_manifest_sha256'],
        binding['motion_profile_manifest_sha256'],
        binding['bounded_call_artifact_sha256'],
        binding['stop_isolation_artifact_sha256'],
        binding['hung_command_stop_report_sha256'],
    )
    if len(set(artifact_hashes)) != len(artifact_hashes):
        raise GripperSafetyLatchError(
            'release, motion-profile and execution-safety artifacts must be '
            'distinct')
    return binding


def _is_reparse(metadata):
    return bool(
        getattr(metadata, 'st_file_attributes', 0)
        & _WINDOWS_REPARSE_POINT)


def _reject_link_or_reparse(metadata, label):
    if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
        raise GripperSafetyLatchError(
            '{} must not be a symbolic link or reparse point'.format(label))


def _stable_file_identity(metadata, label):
    device = getattr(metadata, 'st_dev', None)
    inode = getattr(metadata, 'st_ino', None)
    if type(device) is not int or type(inode) is not int or inode <= 0:
        raise GripperSafetyLatchError(
            '{} stable file identity is unavailable'.format(label))
    return device, inode


def _validate_regular_metadata(metadata, label):
    _reject_link_or_reparse(metadata, label)
    if not stat.S_ISREG(metadata.st_mode):
        raise GripperSafetyLatchError(
            '{} must be an ordinary file'.format(label))
    link_count = getattr(metadata, 'st_nlink', None)
    if type(link_count) is not int or link_count != 1:
        raise GripperSafetyLatchError(
            '{} must have exactly one filesystem link'.format(label))
    return _stable_file_identity(metadata, label)


def _validate_directory_chain(path):
    absolute = Path(os.path.abspath(str(path)))
    anchor = Path(absolute.anchor)
    current = anchor
    parts = absolute.parts
    start = 1 if parts and parts[0] == absolute.anchor else 0
    for part in parts[start:]:
        current = current / part
        try:
            metadata = os.lstat(str(current))
        except OSError as exc:
            raise GripperSafetyLatchError(
                'safety latch directory chain is unavailable') from exc
        _reject_link_or_reparse(metadata, 'safety latch directory chain')
        if not stat.S_ISDIR(metadata.st_mode):
            raise GripperSafetyLatchError(
                'safety latch directory chain contains a non-directory')
    return absolute


def _prepare_store_path(value, must_exist):
    path_type = type(Path('.'))
    if type(value) is str:
        raw = value
    elif type(value) is path_type:
        raw = str(value)
    else:
        raise GripperSafetyLatchError(
            'store path must be an exact string or platform Path')
    normalized = raw.replace('\\', '/').casefold()
    if normalized == '/dev' or normalized.startswith('/dev/'):
        raise GripperSafetyLatchError(
            'device paths are forbidden for safety latch storage')
    if raw.startswith('\\\\.\\') or raw.startswith('\\\\?\\'):
        raise GripperSafetyLatchError(
            'special filesystem namespaces are forbidden')
    path = Path(raw)
    if not path.is_absolute():
        raise GripperSafetyLatchError('store path must be absolute')
    if not path.name or ':' in path.name or path.name.endswith((' ', '.')):
        raise GripperSafetyLatchError('store directory name is unsafe')
    if path.name.split('.', 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise GripperSafetyLatchError('reserved store names are forbidden')
    parent = _validate_directory_chain(path.parent)
    resolved = parent / path.name
    if must_exist:
        try:
            metadata = os.lstat(str(resolved))
        except OSError as exc:
            raise GripperSafetyLatchError(
                'persistent safety latch store is unavailable') from exc
        _reject_link_or_reparse(metadata, 'safety latch store')
        if not stat.S_ISDIR(metadata.st_mode):
            raise GripperSafetyLatchError(
                'persistent safety latch store must be a directory')
    return resolved


def _write_exclusive(path, payload):
    descriptor = None
    created = False
    try:
        descriptor = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise GripperSafetyLatchError(
            'exclusive record creation collided with another writer') from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(str(path))
            except OSError:
                pass
        raise GripperSafetyLatchError(
            'exclusive record write failed') from exc


def _fsync_directory(path):
    if os.name != 'posix':
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_opened_writer_lock(
        descriptor, lock_path, expected_identity=None):
    opened = os.fstat(descriptor)
    opened_identity = _validate_regular_metadata(
        opened, 'persistent writer lock')
    try:
        path_metadata = os.lstat(str(lock_path))
    except OSError as exc:
        raise GripperSafetyLatchError(
            'persistent writer lock path is unavailable') from exc
    path_identity = _validate_regular_metadata(
        path_metadata, 'persistent writer lock')
    if path_identity != opened_identity:
        raise GripperSafetyLatchError(
            'persistent writer lock path changed during acquisition')
    if expected_identity is not None and opened_identity != expected_identity:
        raise GripperSafetyLatchError(
            'persistent writer lock inode changed before acquisition')
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = os.read(descriptor, len(WRITER_LOCK_PAYLOAD) + 1)
    if payload != WRITER_LOCK_PAYLOAD:
        raise GripperSafetyLatchError(
            'persistent writer lock marker is invalid')


def _lock_writer_descriptor(descriptor):
    try:
        if os.name == 'nt':
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        raise GripperSafetyLatchError(
            'persistent writer lock acquisition failed') from exc


def _unlock_writer_descriptor(descriptor):
    try:
        if os.name == 'nt':
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise GripperSafetyLatchError(
            'persistent writer lock release failed') from exc


def _create_writer_lock(store_path):
    lock_path = store_path / WRITER_LOCK_NAME
    _write_exclusive(lock_path, WRITER_LOCK_PAYLOAD)
    _fsync_directory(store_path)


@contextmanager
def _locked_writer(store_path):
    with _PROCESS_WRITER_LOCK:
        store_path = _prepare_store_path(store_path, must_exist=True)
        lock_path = store_path / WRITER_LOCK_NAME
        try:
            metadata = os.lstat(str(lock_path))
        except OSError as exc:
            raise GripperSafetyLatchError(
                'persistent writer lock is unavailable') from exc
        expected_identity = _validate_regular_metadata(
            metadata, 'persistent writer lock')
        flags = os.O_RDWR | getattr(os, 'O_BINARY', 0)
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        descriptor = None
        acquired = False
        try:
            descriptor = os.open(str(lock_path), flags)
            _validate_opened_writer_lock(
                descriptor, lock_path, expected_identity)
            _lock_writer_descriptor(descriptor)
            acquired = True
            _validate_opened_writer_lock(
                descriptor, lock_path, expected_identity)
            yield store_path
            _validate_opened_writer_lock(
                descriptor, lock_path, expected_identity)
        except GripperSafetyLatchError:
            raise
        except OSError as exc:
            raise GripperSafetyLatchError(
                'persistent writer lock operation failed') from exc
        finally:
            try:
                if acquired:
                    _unlock_writer_descriptor(descriptor)
            finally:
                if descriptor is not None:
                    os.close(descriptor)


def _publish_generation(store_path, record, token_factory=None):
    generation = record['payload']['generation']
    final_path = store_path / 'generation-{:020d}'.format(generation)
    factory = (lambda: uuid.uuid4().hex) \
        if token_factory is None else token_factory
    if not callable(factory):
        raise GripperSafetyLatchError('publish token factory must be callable')
    token = _exact_token(factory(), 'publish token')
    pending_path = store_path / '.pending-{}'.format(token)
    transaction_path = store_path / '{}{}'.format(
        _TRANSACTION_PREFIX, token)
    record_path = pending_path / 'record.json'
    transaction_created = False
    try:
        os.mkdir(str(pending_path), 0o700)
        _write_exclusive(record_path, canonical_json_bytes(record))
        _fsync_directory(pending_path)
        transaction_payload = canonical_json_bytes({
            'generation': generation,
            'record_sha256': record['record_sha256'],
        })
        _write_exclusive(transaction_path, transaction_payload)
        transaction_created = True
        # Make the fail-closed transaction marker durable before publication.
        # A restart that observes it refuses to expose any tentative state.
        _fsync_directory(store_path)
        os.rename(str(pending_path), str(final_path))
        # Only this sync commits the generation.  Failure leaves the durable
        # transaction marker in place, so CLEAR cannot become observable via
        # the validated loader after an exception was returned.
        _fsync_directory(store_path)
        # Do not remove the fail-closed marker while the writer context is
        # still validating and releasing its lock.  The caller finishes the
        # publication only after a completely successful context exit.
        return transaction_path, transaction_payload
    except FileExistsError as exc:
        raise GripperSafetyLatchError(
            'generation publication collided with another writer') from exc
    except OSError as exc:
        raise GripperSafetyLatchError(
            'atomic generation publication failed') from exc
    finally:
        if not transaction_created and pending_path.exists():
            try:
                if record_path.exists():
                    os.unlink(str(record_path))
                os.rmdir(str(pending_path))
            except OSError:
                pass
        # Once the transaction exists, cleanup is deliberately forbidden on
        # failure.  Its presence is the durable restart-time BLOCKED latch.


def _finish_generation_publication(store_path, transaction):
    """Expose a committed generation only after writer-context exit succeeds."""
    if type(transaction) is not tuple or len(transaction) != 2:
        raise GripperSafetyLatchError(
            'generation publication evidence is invalid')
    transaction_path, expected_payload = transaction
    if (
            type(transaction_path) is not type(Path('.'))
            or transaction_path.parent != store_path
            or not transaction_path.name.startswith(_TRANSACTION_PREFIX)
            or type(expected_payload) is not bytes
            or not expected_payload):
        raise GripperSafetyLatchError(
            'generation publication evidence is invalid')
    if _read_regular_file_once(transaction_path) != expected_payload:
        raise GripperSafetyLatchError(
            'generation transaction marker changed; state remains BLOCKED')
    try:
        os.unlink(str(transaction_path))
    except OSError as exc:
        raise GripperSafetyLatchError(
            'committed generation cannot clear its transaction marker') \
            from exc
    # Marker removal is the runtime-visible commit point.  Failure to persist
    # its deletion can conservatively re-block after a crash, but must not
    # report an already visible state as a failed call in this process.
    try:
        _fsync_directory(store_path)
    except OSError:
        pass


def _read_regular_file_once(path):
    try:
        path_metadata = os.lstat(str(path))
    except OSError as exc:
        raise GripperSafetyLatchError('record file is unavailable') from exc
    expected_identity = _validate_regular_metadata(
        path_metadata, 'record file')
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        opened_identity = _validate_regular_metadata(opened, 'record file')
        if opened_identity != expected_identity:
            raise GripperSafetyLatchError(
                'record path/inode identity changed before open')
        if opened.st_size < 1 or opened.st_size > MAX_RECORD_BYTES:
            raise GripperSafetyLatchError(
                'record size is outside the bounded contract')
        chunks = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        after_identity = _validate_regular_metadata(after, 'record file')
        payload = b''.join(chunks)
        if (
                remaining
                or after.st_size != opened.st_size
                or after_identity != opened_identity):
            raise GripperSafetyLatchError(
                'record changed during the bounded read')
        try:
            final_path_metadata = os.lstat(str(path))
        except OSError as exc:
            raise GripperSafetyLatchError(
                'record path disappeared after read') from exc
        final_identity = _validate_regular_metadata(
            final_path_metadata, 'record file')
        if final_identity != opened_identity:
            raise GripperSafetyLatchError(
                'record path/inode identity changed during read')
        return payload
    except GripperSafetyLatchError:
        raise
    except OSError as exc:
        raise GripperSafetyLatchError('bounded record read failed') from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


_PAYLOAD_KEYS = (
    'store_id', 'generation', 'event', 'status',
    'previous_record_sha256', 'runtime_release_id',
    'release_manifest_sha256', 'motion_profile_id',
    'motion_profile_manifest_sha256',
    'motion_profile_runtime_release_id', 'approved_speed_grades',
    'bounded_call_artifact_sha256',
    'stop_isolation_artifact_sha256',
    'hung_command_stop_report_sha256',
    'last_session_epoch', 'event_session_epoch', 'event_session_id',
    'event_session_nonce', 'latched_session_epoch',
    'clear_after_session_epoch', 'reason', 'clearance_id',
    'physical_verification_artifact_sha256',
    'approval_artifact_sha256', 'authenticity_limit',
)


def _record_from_payload(payload):
    cloned = _clone_json(payload, 'payload')
    return {
        'schema_version': SCHEMA_VERSION,
        'payload': cloned,
        'record_sha256': hashlib.sha256(
            canonical_json_bytes(cloned)).hexdigest(),
    }


def _validate_record(record):
    record = _exact_keys(
        record, ('schema_version', 'payload', 'record_sha256'), 'record')
    if type(record['schema_version']) is not int:
        raise GripperSafetyLatchError(
            'record.schema_version must be an exact integer')
    if record['schema_version'] != SCHEMA_VERSION:
        raise GripperSafetyLatchError('unsupported record schema version')
    payload = _exact_keys(record['payload'], _PAYLOAD_KEYS, 'record.payload')
    _exact_token(payload['store_id'], 'record.payload.store_id')
    if type(payload['generation']) is not int or payload['generation'] < 0:
        raise GripperSafetyLatchError(
            'record generation must be a non-negative integer')
    if payload['event'] not in (
            'STORE_CREATED', 'SESSION_ISSUED', 'LATCHED', 'CLEARED'):
        raise GripperSafetyLatchError('record event is invalid')
    if payload['status'] not in ('CLEAR', 'ACTIVE'):
        raise GripperSafetyLatchError('record status is invalid')
    previous = payload['previous_record_sha256']
    if previous is not None:
        _exact_sha256(previous, 'record.payload.previous_record_sha256')
    binding = _release_binding(
        payload['runtime_release_id'],
        payload['release_manifest_sha256'],
        payload['motion_profile_id'],
        payload['motion_profile_manifest_sha256'],
        payload['motion_profile_runtime_release_id'],
        payload['approved_speed_grades'],
        payload['bounded_call_artifact_sha256'],
        payload['stop_isolation_artifact_sha256'],
        payload['hung_command_stop_report_sha256'],
    )
    if binding['approved_speed_grades'] != payload['approved_speed_grades']:
        raise GripperSafetyLatchError('record speed grades are not exact')
    for name in ('last_session_epoch', 'event_session_epoch'):
        if type(payload[name]) is not int or payload[name] < 1:
            raise GripperSafetyLatchError(
                'record.payload.{} must be a positive integer'.format(name))
    if payload['event_session_epoch'] > payload['last_session_epoch']:
        raise GripperSafetyLatchError(
            'event session epoch exceeds the issued-session boundary')
    _exact_string(payload['event_session_id'], 'record event session ID')
    _exact_token(payload['event_session_nonce'], 'record event session nonce')
    _exact_string(payload['reason'], 'record reason')
    if payload['authenticity_limit'] != AUTHENTICITY_LIMIT:
        raise GripperSafetyLatchError('record authenticity limit is invalid')
    latch_values = (
        payload['latched_session_epoch'],
        payload['clear_after_session_epoch'],
    )
    clearance_values = (
        payload['clearance_id'],
        payload['physical_verification_artifact_sha256'],
        payload['approval_artifact_sha256'],
    )
    if payload['status'] == 'ACTIVE':
        if not all(type(value) is int and value >= 1 for value in latch_values):
            raise GripperSafetyLatchError(
                'ACTIVE record requires latch session epochs')
        if payload['clear_after_session_epoch'] < payload[
                'latched_session_epoch']:
            raise GripperSafetyLatchError(
                'clear boundary precedes the latching session')
        if any(value is not None for value in clearance_values):
            raise GripperSafetyLatchError(
                'ACTIVE record must not contain clearance evidence')
    elif all(value is None for value in latch_values + clearance_values):
        pass
    elif (
            all(type(value) is int and value >= 1 for value in latch_values)
            and all(value is not None for value in clearance_values)):
        _exact_string(payload['clearance_id'], 'record clearance ID')
        _exact_sha256(
            payload['physical_verification_artifact_sha256'],
            'record physical verification artifact')
        _exact_sha256(
            payload['approval_artifact_sha256'],
            'record approval artifact')
    else:
        raise GripperSafetyLatchError(
            'CLEAR record has incomplete latch or clearance evidence')
    expected = hashlib.sha256(
        canonical_json_bytes(payload)).hexdigest()
    if record['record_sha256'] != expected:
        raise GripperSafetyLatchError('record SHA-256 mismatch')
    return _clone_json(record, 'record')


def _same_state(left, right):
    keys = (
        'status', 'latched_session_epoch', 'clear_after_session_epoch',
        'clearance_id', 'physical_verification_artifact_sha256',
        'approval_artifact_sha256',
    )
    return all(left[key] == right[key] for key in keys)


def _validate_chain(records):
    if not records:
        raise GripperSafetyLatchError('safety latch store has no records')
    sessions = {}
    nonces = set()
    clearance_ids = set()
    previous = None
    binding_keys = (
        'runtime_release_id', 'release_manifest_sha256',
        'motion_profile_id', 'motion_profile_manifest_sha256',
        'motion_profile_runtime_release_id', 'approved_speed_grades',
        'bounded_call_artifact_sha256',
        'stop_isolation_artifact_sha256',
        'hung_command_stop_report_sha256',
    )
    for index, item in enumerate(records):
        record = _validate_record(item)
        payload = record['payload']
        if payload['generation'] != index:
            raise GripperSafetyLatchError(
                'generation sequence is not contiguous')
        if index == 0:
            if (
                    payload['event'] != 'STORE_CREATED'
                    or payload['status'] != 'CLEAR'
                    or payload['previous_record_sha256'] is not None
                    or payload['last_session_epoch'] != 1
                    or payload['event_session_epoch'] != 1
                    or payload['latched_session_epoch'] is not None
                    or payload['clear_after_session_epoch'] is not None
                    or payload['clearance_id'] is not None
                    or payload[
                        'physical_verification_artifact_sha256'] is not None
                    or payload['approval_artifact_sha256'] is not None):
                raise GripperSafetyLatchError(
                    'initial store record is invalid')
            sessions[1] = (
                payload['event_session_id'], payload['event_session_nonce'])
            nonces.add(payload['event_session_nonce'])
            previous = record
            continue
        prior = previous['payload']
        if payload['store_id'] != prior['store_id']:
            raise GripperSafetyLatchError('store identity changed in chain')
        if payload['previous_record_sha256'] != previous['record_sha256']:
            raise GripperSafetyLatchError('record hash chain is broken')
        for key in binding_keys:
            if payload[key] != prior[key]:
                raise GripperSafetyLatchError(
                    'release/profile binding changed in chain')
        event = payload['event']
        actor = (
            payload['event_session_id'], payload['event_session_nonce'])
        if event == 'SESSION_ISSUED':
            expected_epoch = prior['last_session_epoch'] + 1
            if (
                    payload['event_session_epoch'] != expected_epoch
                    or payload['last_session_epoch'] != expected_epoch
                    or not _same_state(payload, prior)):
                raise GripperSafetyLatchError(
                    'session issuance transition is invalid')
            if (
                    payload['event_session_id'] in (
                        value[0] for value in sessions.values())
                    or payload['event_session_nonce'] in nonces):
                raise GripperSafetyLatchError(
                    'session ID and nonce must be unique')
            sessions[expected_epoch] = actor
            nonces.add(actor[1])
        else:
            if payload['last_session_epoch'] != prior['last_session_epoch']:
                raise GripperSafetyLatchError(
                    'non-session event changed session epoch')
            if sessions.get(payload['event_session_epoch']) != actor:
                raise GripperSafetyLatchError(
                    'event actor is not an issued exact session')
            if event == 'LATCHED':
                if (
                        prior['status'] not in ('CLEAR', 'ACTIVE')
                        or payload['status'] != 'ACTIVE'
                        or payload['latched_session_epoch']
                        != payload['event_session_epoch']
                        or payload['clear_after_session_epoch']
                        != prior['last_session_epoch']):
                    raise GripperSafetyLatchError(
                        'latch transition is invalid')
            elif event == 'CLEARED':
                clearance_id = payload['clearance_id']
                if (
                        prior['status'] != 'ACTIVE'
                        or payload['status'] != 'CLEAR'
                        or payload['latched_session_epoch']
                        != prior['latched_session_epoch']
                        or payload['clear_after_session_epoch']
                        != prior['clear_after_session_epoch']
                        or payload['event_session_epoch']
                        <= prior['clear_after_session_epoch']
                        or payload['event_session_epoch']
                        != prior['last_session_epoch']
                        or clearance_id in clearance_ids):
                    raise GripperSafetyLatchError(
                        'clear transition is invalid or replayed')
                clearance_ids.add(clearance_id)
            else:
                raise GripperSafetyLatchError(
                    'STORE_CREATED may appear only at generation zero')
        previous = record
    return records[-1], sessions, frozenset(clearance_ids)


def _load_store(store_path):
    try:
        entries = list(os.scandir(str(store_path)))
    except OSError as exc:
        raise GripperSafetyLatchError(
            'safety latch store cannot be enumerated') from exc
    generations = []
    writer_lock_seen = False
    for entry in entries:
        if entry.name == WRITER_LOCK_NAME:
            metadata = os.lstat(entry.path)
            _reject_link_or_reparse(metadata, 'persistent writer lock')
            if not stat.S_ISREG(metadata.st_mode):
                raise GripperSafetyLatchError(
                    'persistent writer lock must be an ordinary file')
            writer_lock_seen = True
            continue
        match = _GENERATION_NAME.fullmatch(entry.name)
        if match is None:
            if (
                    entry.name.startswith(_TRANSACTION_PREFIX)
                    or entry.name.startswith('.pending-')):
                raise GripperSafetyLatchError(
                    'incomplete publication transaction; safety state is '
                    'BLOCKED')
            raise GripperSafetyLatchError(
                'store contains an unknown or pending entry')
        metadata = os.lstat(entry.path)
        _reject_link_or_reparse(metadata, 'generation entry')
        if not stat.S_ISDIR(metadata.st_mode):
            raise GripperSafetyLatchError(
                'generation entry must be an ordinary directory')
        generations.append((int(match.group(1)), Path(entry.path)))
    if not writer_lock_seen:
        raise GripperSafetyLatchError(
            'persistent writer lock is missing')
    generations.sort(key=lambda item: item[0])
    records = []
    for expected, (number, generation_path) in enumerate(generations):
        if number != expected:
            raise GripperSafetyLatchError(
                'generation directory sequence is not contiguous')
        children = list(os.scandir(str(generation_path)))
        if len(children) != 1 or children[0].name != 'record.json':
            raise GripperSafetyLatchError(
                'generation directory contents are not exact')
        records.append(_strict_loads(
            _read_regular_file_once(generation_path / 'record.json')))
    return _validate_chain(records)


def _validate_expected_binding(current, expected):
    payload = current['payload']
    for key, value in expected.items():
        if payload[key] != value or type(payload[key]) is not type(value):
            raise GripperSafetyLatchError(
                'persistent latch release/profile/execution binding is stale')


class PersistentGripperSafetyLatch:
    """Append-only persistent latch bound to one issued process session."""

    def __init__(self, path, binding, session):
        self._path = path
        self._binding = _clone_json(binding, 'binding')
        self._session = _clone_json(session, 'session')
        self._thread_lock = threading.RLock()

    @classmethod
    def create(
            cls, path, session_id, runtime_release_id,
            release_manifest_sha256, motion_profile_id,
            motion_profile_manifest_sha256,
            motion_profile_runtime_release_id, approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256,
            store_id_factory=None, session_nonce_factory=None):
        """Exclusively create a store and its first issued session."""
        store_path = _prepare_store_path(path, must_exist=False)
        binding = _release_binding(
            runtime_release_id, release_manifest_sha256, motion_profile_id,
            motion_profile_manifest_sha256,
            motion_profile_runtime_release_id, approved_speed_grades,
            bounded_call_artifact_sha256,
            stop_isolation_artifact_sha256,
            hung_command_stop_report_sha256)
        session_id = _exact_string(session_id, 'session_id')
        try:
            os.mkdir(str(store_path), 0o700)
        except FileExistsError as exc:
            raise GripperSafetyLatchError(
                'safety latch store already exists; overwrite is forbidden') \
                from exc
        except OSError as exc:
            raise GripperSafetyLatchError(
                'exclusive safety latch store creation failed') from exc
        # The exclusive namespace reservation must precede all caller-owned
        # factories.  A duplicate create therefore cannot consume IDs/nonces
        # or trigger arbitrary factory side effects.
        store_factory = (lambda: uuid.uuid4().hex) \
            if store_id_factory is None else store_id_factory
        nonce_factory = (lambda: uuid.uuid4().hex) \
            if session_nonce_factory is None else session_nonce_factory
        if not callable(store_factory):
            raise GripperSafetyLatchError(
                'store ID factory must be callable')
        if not callable(nonce_factory):
            raise GripperSafetyLatchError(
                'session nonce factory must be callable')
        store_id = _exact_token(store_factory(), 'store ID')
        nonce = _exact_token(nonce_factory(), 'session nonce')
        payload = {
            'store_id': store_id,
            'generation': 0,
            'event': 'STORE_CREATED',
            'status': 'CLEAR',
            'previous_record_sha256': None,
            'runtime_release_id': binding['runtime_release_id'],
            'release_manifest_sha256': binding[
                'release_manifest_sha256'],
            'motion_profile_id': binding['motion_profile_id'],
            'motion_profile_manifest_sha256': binding[
                'motion_profile_manifest_sha256'],
            'motion_profile_runtime_release_id': binding[
                'motion_profile_runtime_release_id'],
            'approved_speed_grades': binding['approved_speed_grades'],
            'bounded_call_artifact_sha256': binding[
                'bounded_call_artifact_sha256'],
            'stop_isolation_artifact_sha256': binding[
                'stop_isolation_artifact_sha256'],
            'hung_command_stop_report_sha256': binding[
                'hung_command_stop_report_sha256'],
            'last_session_epoch': 1,
            'event_session_epoch': 1,
            'event_session_id': session_id,
            'event_session_nonce': nonce,
            'latched_session_epoch': None,
            'clear_after_session_epoch': None,
            'reason': 'persistent gripper safety latch store initialized',
            'clearance_id': None,
            'physical_verification_artifact_sha256': None,
            'approval_artifact_sha256': None,
            'authenticity_limit': AUTHENTICITY_LIMIT,
        }
        record = _validate_record(_record_from_payload(payload))
        with _PROCESS_WRITER_LOCK:
            _create_writer_lock(store_path)
            with _locked_writer(store_path):
                transaction = _publish_generation(store_path, record)
            _finish_generation_publication(store_path, transaction)
        return cls(store_path, binding, {
            'epoch': 1, 'session_id': session_id, 'nonce': nonce})

    @classmethod
    def open(
            cls, path, session_id, expected_runtime_release_id,
            expected_release_manifest_sha256, expected_motion_profile_id,
            expected_motion_profile_manifest_sha256,
            expected_motion_profile_runtime_release_id,
            expected_approved_speed_grades,
            expected_bounded_call_artifact_sha256,
            expected_stop_isolation_artifact_sha256,
            expected_hung_command_stop_report_sha256,
            session_nonce_factory=None):
        """Validate exact binding, then append one newly issued session."""
        store_path = _prepare_store_path(path, must_exist=True)
        binding = _release_binding(
            expected_runtime_release_id,
            expected_release_manifest_sha256,
            expected_motion_profile_id,
            expected_motion_profile_manifest_sha256,
            expected_motion_profile_runtime_release_id,
            expected_approved_speed_grades,
            expected_bounded_call_artifact_sha256,
            expected_stop_isolation_artifact_sha256,
            expected_hung_command_stop_report_sha256)
        session_id = _exact_string(session_id, 'session_id')
        nonce_factory = (lambda: uuid.uuid4().hex) \
            if session_nonce_factory is None else session_nonce_factory
        if not callable(nonce_factory):
            raise GripperSafetyLatchError(
                'session nonce factory must be callable')
        nonce = _exact_token(nonce_factory(), 'session nonce')
        with _PROCESS_WRITER_LOCK:
            with _locked_writer(store_path):
                current, sessions, unused_clearance_ids = _load_store(store_path)
                _validate_expected_binding(current, binding)
                if session_id in (value[0] for value in sessions.values()):
                    raise GripperSafetyLatchError(
                        'session ID was already issued; reuse is forbidden')
                if nonce in (value[1] for value in sessions.values()):
                    raise GripperSafetyLatchError(
                        'session nonce was already issued; reuse is forbidden')
                epoch = current['payload']['last_session_epoch'] + 1
                payload = _clone_json(current['payload'])
                payload.update({
                    'generation': payload['generation'] + 1,
                    'event': 'SESSION_ISSUED',
                    'previous_record_sha256': current['record_sha256'],
                    'last_session_epoch': epoch,
                    'event_session_epoch': epoch,
                    'event_session_id': session_id,
                    'event_session_nonce': nonce,
                    'reason': 'persistent process session issued',
                })
                record = _validate_record(_record_from_payload(payload))
                transaction = _publish_generation(store_path, record)
            _finish_generation_publication(store_path, transaction)
        return cls(store_path, binding, {
            'epoch': epoch, 'session_id': session_id, 'nonce': nonce})

    @property
    def path(self):
        return self._path

    def _load_bound_store(self):
        current, sessions, clearance_ids = _load_store(self._path)
        _validate_expected_binding(current, self._binding)
        expected_session = (
            self._session['session_id'], self._session['nonce'])
        if sessions.get(self._session['epoch']) != expected_session:
            raise GripperSafetyLatchError(
                'bound process session is absent or forged')
        return current, sessions, clearance_ids

    def _require_latest_session(self, current, sessions):
        expected_session = (
            self._session['session_id'], self._session['nonce'])
        if (
                current['payload']['last_session_epoch']
                != self._session['epoch']
                or sessions.get(self._session['epoch'])
                != expected_session):
            raise GripperSafetyLatchError(
                'only the latest issued process session may clear the latch')

    def snapshot(self):
        """Return the current validated record and reject stale binding."""
        with self._thread_lock, _locked_writer(self._path):
            current, unused_sessions, unused_clearance_ids = \
                self._load_bound_store()
            return current

    @property
    def active(self):
        return self.snapshot()['payload']['status'] == 'ACTIVE'

    def latch(self, reason):
        """Append ACTIVE without deleting or rewriting prior generations."""
        reason = _exact_string(reason, 'latch reason')
        with _PROCESS_WRITER_LOCK:
            with self._thread_lock, _locked_writer(self._path):
                current, unused_sessions, unused_clearance_ids = \
                    self._load_bound_store()
                payload = _clone_json(current['payload'])
                payload.update({
                    'generation': payload['generation'] + 1,
                    'event': 'LATCHED',
                    'status': 'ACTIVE',
                    'previous_record_sha256': current['record_sha256'],
                    'event_session_epoch': self._session['epoch'],
                    'event_session_id': self._session['session_id'],
                    'event_session_nonce': self._session['nonce'],
                    'latched_session_epoch': self._session['epoch'],
                    'clear_after_session_epoch': payload['last_session_epoch'],
                    'reason': reason,
                    'clearance_id': None,
                    'physical_verification_artifact_sha256': None,
                    'approval_artifact_sha256': None,
                })
                record = _validate_record(_record_from_payload(payload))
                transaction = _publish_generation(self._path, record)
            _finish_generation_publication(self._path, transaction)
        return record

    def build_clearance_credential(
            self, clearance_id,
            physical_verification_artifact_sha256,
            approval_artifact_sha256):
        """Bind a clearance request to a post-latch issued session."""
        clearance_id = _exact_string(clearance_id, 'clearance_id')
        with self._thread_lock, _locked_writer(self._path):
            current, sessions, clearance_ids = self._load_bound_store()
            payload = current['payload']
            if payload['status'] != 'ACTIVE':
                raise GripperSafetyLatchError(
                    'no active latch can be cleared')
            self._require_latest_session(current, sessions)
            if self._session['epoch'] <= payload['clear_after_session_epoch']:
                raise GripperSafetyLatchError(
                    'session predates or created the latch and cannot clear it')
            if clearance_id in clearance_ids:
                raise GripperSafetyLatchError(
                    'clearance ID was already committed; replay is forbidden')
            return {
                'schema_version': CREDENTIAL_SCHEMA_VERSION,
                'store_id': payload['store_id'],
                'expected_generation': payload['generation'],
                'expected_record_sha256': current['record_sha256'],
                'latched_session_epoch': payload['latched_session_epoch'],
                'clear_after_session_epoch': payload[
                    'clear_after_session_epoch'],
                'clearing_session_epoch': self._session['epoch'],
                'clearing_session_id': self._session['session_id'],
                'clearing_session_nonce': self._session['nonce'],
                'runtime_release_id': payload['runtime_release_id'],
                'release_manifest_sha256': payload[
                    'release_manifest_sha256'],
                'motion_profile_id': payload['motion_profile_id'],
                'motion_profile_manifest_sha256': payload[
                    'motion_profile_manifest_sha256'],
                'motion_profile_runtime_release_id': payload[
                    'motion_profile_runtime_release_id'],
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
                    'physical_verification_artifact_sha256'),
                'approval_artifact_sha256': _exact_sha256(
                    approval_artifact_sha256,
                    'approval_artifact_sha256'),
                'authenticity_limit': AUTHENTICITY_LIMIT,
            }

    def _validate_credential(self, credential, current):
        credential = _clone_json(credential, 'credential')
        keys = (
            'schema_version', 'store_id', 'expected_generation',
            'expected_record_sha256', 'latched_session_epoch',
            'clear_after_session_epoch', 'clearing_session_epoch',
            'clearing_session_id', 'clearing_session_nonce',
            'runtime_release_id', 'release_manifest_sha256',
            'motion_profile_id', 'motion_profile_manifest_sha256',
            'motion_profile_runtime_release_id', 'approved_speed_grades',
            'bounded_call_artifact_sha256',
            'stop_isolation_artifact_sha256',
            'hung_command_stop_report_sha256',
            'clearance_id',
            'physical_verification_artifact_sha256',
            'approval_artifact_sha256', 'authenticity_limit',
        )
        _exact_keys(credential, keys, 'credential')
        if (
                type(credential['schema_version']) is not int
                or credential['schema_version']
                != CREDENTIAL_SCHEMA_VERSION):
            raise GripperSafetyLatchError(
                'clearance credential schema is invalid')
        payload = current['payload']
        expected = {
            'store_id': payload['store_id'],
            'expected_generation': payload['generation'],
            'expected_record_sha256': current['record_sha256'],
            'latched_session_epoch': payload['latched_session_epoch'],
            'clear_after_session_epoch': payload[
                'clear_after_session_epoch'],
            'clearing_session_epoch': self._session['epoch'],
            'clearing_session_id': self._session['session_id'],
            'clearing_session_nonce': self._session['nonce'],
            'runtime_release_id': payload['runtime_release_id'],
            'release_manifest_sha256': payload[
                'release_manifest_sha256'],
            'motion_profile_id': payload['motion_profile_id'],
            'motion_profile_manifest_sha256': payload[
                'motion_profile_manifest_sha256'],
            'motion_profile_runtime_release_id': payload[
                'motion_profile_runtime_release_id'],
            'approved_speed_grades': payload['approved_speed_grades'],
            'bounded_call_artifact_sha256': payload[
                'bounded_call_artifact_sha256'],
            'stop_isolation_artifact_sha256': payload[
                'stop_isolation_artifact_sha256'],
            'hung_command_stop_report_sha256': payload[
                'hung_command_stop_report_sha256'],
            'authenticity_limit': AUTHENTICITY_LIMIT,
        }
        for key, value in expected.items():
            if (
                    credential[key] != value
                    or type(credential[key]) is not type(value)):
                raise GripperSafetyLatchError(
                    'clearance credential is stale or forged')
        if self._session['epoch'] <= payload['clear_after_session_epoch']:
            raise GripperSafetyLatchError(
                'session predates or created the latch and cannot clear it')
        _exact_string(credential['clearance_id'], 'credential clearance ID')
        _exact_sha256(
            credential['physical_verification_artifact_sha256'],
            'credential physical verification artifact')
        _exact_sha256(
            credential['approval_artifact_sha256'],
            'credential approval artifact')
        return credential

    def clear(self, credential, approval_validator=None):
        """Append CLEAR only after exact external validation and recheck."""
        with self._thread_lock, _locked_writer(self._path):
            current, sessions, clearance_ids = self._load_bound_store()
            if current['payload']['status'] != 'ACTIVE':
                raise GripperSafetyLatchError(
                    'no active latch can be cleared')
            self._require_latest_session(current, sessions)
            normalized = self._validate_credential(credential, current)
            if normalized['clearance_id'] in clearance_ids:
                raise GripperSafetyLatchError(
                    'clearance ID was already committed; replay is forbidden')
            if approval_validator is None:
                raise GripperSafetyLatchError(
                    'external approval validator is required')
        try:
            accepted = approval_validator(
                _clone_json(normalized, 'credential'),
                _clone_json(current, 'record'))
        except Exception as exc:
            raise GripperSafetyLatchError(
                'external clearance validation failed') from exc
        if accepted is not True:
            raise GripperSafetyLatchError(
                'external clearance validation did not return exact True')
        with _PROCESS_WRITER_LOCK:
            with self._thread_lock, _locked_writer(self._path):
                latest, sessions, clearance_ids = self._load_bound_store()
                self._require_latest_session(latest, sessions)
                if (
                        latest['record_sha256']
                        != normalized['expected_record_sha256']
                        or latest['payload']['generation']
                        != normalized['expected_generation']):
                    raise GripperSafetyLatchError(
                        'clearance credential became stale before commit')
                self._validate_credential(normalized, latest)
                if normalized['clearance_id'] in clearance_ids:
                    raise GripperSafetyLatchError(
                        'clearance ID was already committed; replay is forbidden')
                payload = _clone_json(latest['payload'])
                payload.update({
                    'generation': payload['generation'] + 1,
                    'event': 'CLEARED',
                    'status': 'CLEAR',
                    'previous_record_sha256': latest['record_sha256'],
                    'event_session_epoch': self._session['epoch'],
                    'event_session_id': self._session['session_id'],
                    'event_session_nonce': self._session['nonce'],
                    'reason': 'externally approved physical clearance recorded',
                    'clearance_id': normalized['clearance_id'],
                    'physical_verification_artifact_sha256': normalized[
                        'physical_verification_artifact_sha256'],
                    'approval_artifact_sha256': normalized[
                        'approval_artifact_sha256'],
                })
                record = _validate_record(_record_from_payload(payload))
                transaction = _publish_generation(self._path, record)
            _finish_generation_publication(self._path, transaction)
        return record
