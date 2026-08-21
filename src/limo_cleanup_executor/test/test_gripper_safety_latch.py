import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from limo_cleanup_executor.gripper_safety_latch import (  # noqa
    AUTHENTICITY_LIMIT,
    GripperSafetyLatchError,
    PersistentGripperSafetyLatch,
    canonical_json_bytes,
)
import limo_cleanup_executor.gripper_safety_latch as latch_module  # noqa


MODULE = (
    PACKAGE_ROOT / 'limo_cleanup_executor' / 'gripper_safety_latch.py')
RELEASE_HASH = 'a' * 64
PROFILE_HASH = 'b' * 64
PHYSICAL_HASH = 'c' * 64
APPROVAL_HASH = 'd' * 64
BOUNDED_CALL_HASH = 'e' * 64
STOP_ISOLATION_HASH = 'f' * 64
HUNG_STOP_HASH = '0' * 64


def binding_arguments():
    return {
        'runtime_release_id': 'gripper-runtime-r1',
        'release_manifest_sha256': RELEASE_HASH,
        'motion_profile_id': 'gripper-profile-r1',
        'motion_profile_manifest_sha256': PROFILE_HASH,
        'motion_profile_runtime_release_id': 'gripper-runtime-r1',
        'approved_speed_grades': [5, 10],
        'bounded_call_artifact_sha256': BOUNDED_CALL_HASH,
        'stop_isolation_artifact_sha256': STOP_ISOLATION_HASH,
        'hung_command_stop_report_sha256': HUNG_STOP_HASH,
    }


def expected_binding_arguments():
    arguments = binding_arguments()
    return {
        'expected_runtime_release_id': arguments['runtime_release_id'],
        'expected_release_manifest_sha256': arguments[
            'release_manifest_sha256'],
        'expected_motion_profile_id': arguments['motion_profile_id'],
        'expected_motion_profile_manifest_sha256': arguments[
            'motion_profile_manifest_sha256'],
        'expected_motion_profile_runtime_release_id': arguments[
            'motion_profile_runtime_release_id'],
        'expected_approved_speed_grades': arguments[
            'approved_speed_grades'],
        'expected_bounded_call_artifact_sha256': arguments[
            'bounded_call_artifact_sha256'],
        'expected_stop_isolation_artifact_sha256': arguments[
            'stop_isolation_artifact_sha256'],
        'expected_hung_command_stop_report_sha256': arguments[
            'hung_command_stop_report_sha256'],
    }


def create_store(root, session_id='session-a', nonce='nonce-session-a'):
    path = Path(root) / 'gripper-safety-latch'
    store = PersistentGripperSafetyLatch.create(
        path,
        session_id,
        store_id_factory=lambda: 'store-001',
        session_nonce_factory=lambda: nonce,
        **binding_arguments()
    )
    return store, path


def open_store(path, session_id, nonce):
    return PersistentGripperSafetyLatch.open(
        path,
        session_id,
        session_nonce_factory=lambda: nonce,
        **expected_binding_arguments()
    )


def rewrite_generation_chain_binding(path, mutations):
    """Rewrite a whole local chain with valid hashes for tamper tests."""
    previous_record_sha256 = None
    for generation in sorted(Path(path).glob('generation-*')):
        record_path = generation / 'record.json'
        record = json.loads(record_path.read_text(encoding='utf-8'))
        payload = record['payload']
        payload.update(copy.deepcopy(mutations))
        payload['previous_record_sha256'] = previous_record_sha256
        rewritten = latch_module._record_from_payload(payload)
        record_path.write_bytes(canonical_json_bytes(rewritten))
        previous_record_sha256 = rewritten['record_sha256']


@contextmanager
def fail_store_sync_after_generation_rename(store_path):
    """Inject the ambiguous historical failure immediately after rename."""
    original_rename = latch_module.os.rename
    original_sync = latch_module._fsync_directory
    state = {'renamed': False, 'injected': False}

    def controlled_rename(source, destination):
        result = original_rename(source, destination)
        if (
                Path(destination).parent == Path(store_path)
                and Path(destination).name.startswith('generation-')):
            state['renamed'] = True
        return result

    def controlled_sync(path):
        if (
                state['renamed']
                and not state['injected']
                and Path(path) == Path(store_path)):
            state['injected'] = True
            raise OSError('injected post-rename store sync failure')
        return original_sync(path)

    with mock.patch.object(
            latch_module.os, 'rename', side_effect=controlled_rename), \
            mock.patch.object(
                latch_module, '_fsync_directory',
                side_effect=controlled_sync):
        yield
    if not state['injected']:
        raise AssertionError('post-rename sync failure was not injected')


@contextmanager
def fail_cleanup_sync_after_transaction_unlink(store_path):
    """Fail only the non-critical sync after durable commit and marker unlink."""
    original_unlink = latch_module.os.unlink
    original_sync = latch_module._fsync_directory
    state = {'marker_removed': False, 'injected': False}

    def controlled_unlink(path):
        result = original_unlink(path)
        if Path(path).name.startswith('.transaction-'):
            state['marker_removed'] = True
        return result

    def controlled_sync(path):
        if (
                state['marker_removed']
                and not state['injected']
                and Path(path) == Path(store_path)):
            state['injected'] = True
            raise OSError('injected post-commit cleanup sync failure')
        return original_sync(path)

    with mock.patch.object(
            latch_module.os, 'unlink', side_effect=controlled_unlink), \
            mock.patch.object(
                latch_module, '_fsync_directory',
                side_effect=controlled_sync):
        yield
    if not state['injected']:
        raise AssertionError('post-commit cleanup failure was not injected')


@contextmanager
def fail_writer_context_exit(store_path, failure_kind):
    """Fail after publication but before the transaction marker is cleared."""
    original_validate = latch_module._validate_opened_writer_lock
    original_unlock = latch_module._unlock_writer_descriptor
    state = {'injected': False}

    def transaction_exists():
        return any(
            item.name.startswith('.transaction-')
            for item in Path(store_path).iterdir())

    def controlled_validate(
            descriptor, lock_path, expected_identity=None):
        result = original_validate(
            descriptor, lock_path, expected_identity)
        if (
                failure_kind == 'exit-validation'
                and not state['injected']
                and transaction_exists()):
            state['injected'] = True
            raise GripperSafetyLatchError(
                'injected writer context exit validation failure')
        return result

    def controlled_unlock(descriptor):
        result = original_unlock(descriptor)
        if (
                failure_kind == 'unlock'
                and not state['injected']
                and transaction_exists()):
            state['injected'] = True
            raise GripperSafetyLatchError(
                'injected writer context unlock failure')
        return result

    with mock.patch.object(
            latch_module, '_validate_opened_writer_lock',
            side_effect=controlled_validate), mock.patch.object(
                latch_module, '_unlock_writer_descriptor',
                side_effect=controlled_unlock):
        yield
    if not state['injected']:
        raise AssertionError(
            'writer context {} failure was not injected'.format(
                failure_kind))


class PersistentGripperSafetyLatchTest(unittest.TestCase):
    def test_python38_ast_and_no_ros_vendor_or_network_imports(self):
        source = MODULE.read_text(encoding='utf-8')
        tree = ast.parse(
            source, filename=str(MODULE), feature_version=(3, 8))
        forbidden = {'rclpy', 'serial', 'pymycobot', 'socket'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split('.')[0], forbidden)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    (node.module or '').split('.')[0], forbidden)

    def test_create_is_exclusive_and_generation_zero_is_canonical(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            record = store.snapshot()
            record_path = path / 'generation-00000000000000000000' \
                / 'record.json'
            self.assertEqual(record['payload']['generation'], 0)
            self.assertEqual(record['payload']['last_session_epoch'], 1)
            self.assertEqual(
                record_path.read_bytes(), canonical_json_bytes(record))
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'already exists'):
                create_store(root, session_id='session-b')

    def test_duplicate_create_rejects_before_id_or_nonce_factories(self):
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            class SideEffectFactory:
                def __init__(self, label):
                    self.label = label
                    self.bool_calls = 0
                    self.call_calls = 0

                def __bool__(self):
                    self.bool_calls += 1
                    raise AssertionError(
                        '{} factory truthiness was evaluated'.format(
                            self.label))

                def __call__(self):
                    self.call_calls += 1
                    raise AssertionError(
                        'duplicate create consumed {}'.format(self.label))

            forbidden_store_id = SideEffectFactory('store ID')
            forbidden_nonce = SideEffectFactory('session nonce')

            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'already exists'):
                PersistentGripperSafetyLatch.create(
                    path,
                    'session-duplicate',
                    store_id_factory=forbidden_store_id,
                    session_nonce_factory=forbidden_nonce,
                    **binding_arguments()
                )
            self.assertEqual(forbidden_store_id.bool_calls, 0)
            self.assertEqual(forbidden_store_id.call_calls, 0)
            self.assertEqual(forbidden_nonce.bool_calls, 0)
            self.assertEqual(forbidden_nonce.call_calls, 0)

    def test_fresh_create_factories_are_called_without_truthiness(self):
        with tempfile.TemporaryDirectory() as root:
            class SideEffectFactory:
                def __init__(self, value):
                    self.value = value
                    self.bool_calls = 0
                    self.call_calls = 0

                def __bool__(self):
                    self.bool_calls += 1
                    raise AssertionError('factory truthiness was evaluated')

                def __call__(self):
                    self.call_calls += 1
                    return self.value

            store_factory = SideEffectFactory('store-factory-001')
            nonce_factory = SideEffectFactory('nonce-factory-001')
            path = Path(root) / 'gripper-safety-latch'
            store = PersistentGripperSafetyLatch.create(
                path, 'session-factory',
                store_id_factory=store_factory,
                session_nonce_factory=nonce_factory,
                **binding_arguments()
            )
            self.assertEqual(store_factory.bool_calls, 0)
            self.assertEqual(store_factory.call_calls, 1)
            self.assertEqual(nonce_factory.bool_calls, 0)
            self.assertEqual(nonce_factory.call_calls, 1)
            self.assertEqual(
                store.snapshot()['payload']['store_id'],
                'store-factory-001')

    def test_writer_context_exit_failure_keeps_publication_blocked(self):
        for failure_kind in ('exit-validation', 'unlock'):
            for operation in ('create', 'latch', 'clear'):
                with self.subTest(
                        failure_kind=failure_kind, operation=operation), \
                        tempfile.TemporaryDirectory() as root:
                    path = Path(root) / 'gripper-safety-latch'
                    if operation == 'create':
                        with fail_writer_context_exit(path, failure_kind), \
                                self.assertRaisesRegex(
                                    GripperSafetyLatchError, 'injected writer'):
                            create_store(root)
                    else:
                        creator, path = create_store(root)
                        if operation == 'latch':
                            with fail_writer_context_exit(
                                    path, failure_kind), \
                                    self.assertRaisesRegex(
                                        GripperSafetyLatchError,
                                        'injected writer'):
                                creator.latch(
                                    'writer context exit is unverified')
                        else:
                            creator.latch('physical isolation required')
                            clearer = open_store(
                                path, 'session-clearer', 'nonce-clearer')
                            credential = clearer.build_clearance_credential(
                                'clear-writer-exit',
                                PHYSICAL_HASH, APPROVAL_HASH)
                            with fail_writer_context_exit(
                                    path, failure_kind), \
                                    self.assertRaisesRegex(
                                        GripperSafetyLatchError,
                                        'injected writer'):
                                clearer.clear(
                                    credential,
                                    approval_validator=lambda *_: True)
                    transaction_entries = [
                        item for item in path.iterdir()
                        if item.name.startswith('.transaction-')]
                    self.assertEqual(len(transaction_entries), 1)
                    with self.assertRaisesRegex(
                            GripperSafetyLatchError,
                            'incomplete publication transaction.*BLOCKED'):
                        open_store(
                            path,
                            'session-restart-{}-{}'.format(
                                failure_kind, operation),
                            'nonce-restart-{}-{}'.format(
                                failure_kind, operation))

    def test_post_rename_sync_failure_blocks_create_latch_and_clear_restart(
            self):
        operations = ('create', 'latch', 'clear')
        for operation in operations:
            with self.subTest(operation=operation), \
                    tempfile.TemporaryDirectory() as root:
                path = Path(root) / 'gripper-safety-latch'
                if operation == 'create':
                    with fail_store_sync_after_generation_rename(path), \
                            self.assertRaisesRegex(
                                GripperSafetyLatchError,
                                'atomic generation publication failed'):
                        create_store(root)
                else:
                    creator, path = create_store(root)
                    if operation == 'latch':
                        with fail_store_sync_after_generation_rename(path), \
                                self.assertRaisesRegex(
                                    GripperSafetyLatchError,
                                    'atomic generation publication failed'):
                            creator.latch(
                                'post-rename durability is unconfirmed')
                    else:
                        creator.latch('physical isolation required')
                        clearer = open_store(
                            path, 'session-clearer', 'nonce-clearer')
                        credential = clearer.build_clearance_credential(
                            'clear-post-rename', PHYSICAL_HASH, APPROVAL_HASH)
                        with fail_store_sync_after_generation_rename(path), \
                                self.assertRaisesRegex(
                                    GripperSafetyLatchError,
                                    'atomic generation publication failed'):
                            clearer.clear(
                                credential,
                                approval_validator=lambda *_: True)

                transaction_entries = [
                    item for item in path.iterdir()
                    if item.name.startswith('.transaction-')]
                self.assertEqual(len(transaction_entries), 1)
                self.assertTrue(any(
                    item.name.startswith('generation-')
                    for item in path.iterdir()))
                with self.assertRaisesRegex(
                        GripperSafetyLatchError,
                        'incomplete publication transaction.*BLOCKED'):
                    open_store(
                        path,
                        'session-restart-{}'.format(operation),
                        'nonce-restart-{}'.format(operation))

    def test_post_commit_marker_cleanup_sync_failure_returns_visible_state(
            self):
        for operation in ('create', 'latch', 'clear'):
            with self.subTest(operation=operation), \
                    tempfile.TemporaryDirectory() as root:
                path = Path(root) / 'gripper-safety-latch'
                if operation == 'create':
                    with fail_cleanup_sync_after_transaction_unlink(path):
                        store, path = create_store(root)
                    result = store.snapshot()
                    expected_status = 'CLEAR'
                else:
                    creator, path = create_store(root)
                    if operation == 'latch':
                        with fail_cleanup_sync_after_transaction_unlink(path):
                            result = creator.latch(
                                'physical isolation required')
                        store = creator
                        expected_status = 'ACTIVE'
                    else:
                        creator.latch('physical isolation required')
                        clearer = open_store(
                            path, 'session-clearer',
                            'nonce-session-clearer')
                        credential = clearer.build_clearance_credential(
                            'clear-cleanup-sync',
                            PHYSICAL_HASH, APPROVAL_HASH)
                        with fail_cleanup_sync_after_transaction_unlink(path):
                            result = clearer.clear(
                                credential,
                                approval_validator=lambda *_: True)
                        store = clearer
                        expected_status = 'CLEAR'
                self.assertEqual(
                    result['payload']['status'], expected_status)
                self.assertFalse(any(
                    item.name.startswith('.transaction-')
                    for item in path.iterdir()))
                self.assertEqual(
                    store.snapshot()['record_sha256'],
                    result['record_sha256'])

    def test_device_paths_are_rejected_before_metadata_access(self):
        for value in ('/dev', '/dev/elephant', '\\dev\\ttyUSB0'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    GripperSafetyLatchError, 'device paths are forbidden'):
                PersistentGripperSafetyLatch.open(
                    value, 'session-b',
                    **expected_binding_arguments())

    def test_restart_restores_active_latch_and_exact_binding(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            active = creator.latch('software STOP cannot prove isolation')
            restarted = open_store(
                path, 'session-b', 'nonce-session-b')
            observed = restarted.snapshot()
            self.assertTrue(restarted.active)
            self.assertEqual(observed['payload']['generation'], 2)
            self.assertEqual(
                observed['payload']['previous_record_sha256'],
                active['record_sha256'])
            for key, value in binding_arguments().items():
                self.assertEqual(observed['payload'][key], value)
                self.assertIs(type(observed['payload'][key]), type(value))

    def test_fresh_subprocess_issues_new_session_and_restores_active_latch(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('software STOP cannot prove isolation')
            script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from limo_cleanup_executor.gripper_safety_latch import PersistentGripperSafetyLatch
store = PersistentGripperSafetyLatch.open(
    Path(sys.argv[2]),
    'session-subprocess',
    expected_runtime_release_id='gripper-runtime-r1',
    expected_release_manifest_sha256='a' * 64,
    expected_motion_profile_id='gripper-profile-r1',
    expected_motion_profile_manifest_sha256='b' * 64,
    expected_motion_profile_runtime_release_id='gripper-runtime-r1',
    expected_approved_speed_grades=[5, 10],
    expected_bounded_call_artifact_sha256='e' * 64,
    expected_stop_isolation_artifact_sha256='f' * 64,
    expected_hung_command_stop_report_sha256='0' * 64,
    session_nonce_factory=lambda: 'nonce-session-subprocess')
print(json.dumps(store.snapshot()['payload'], sort_keys=True))
"""
            completed = subprocess.run(
                [sys.executable, '-c', script, str(PACKAGE_ROOT), str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            observed = json.loads(completed.stdout)
            self.assertEqual(observed['status'], 'ACTIVE')
            self.assertEqual(observed['generation'], 2)
            self.assertEqual(observed['last_session_epoch'], 2)
            self.assertTrue(creator.active)

    def test_open_rejects_stale_full_release_profile_execution_binding(self):
        mutations = (
            ('expected_runtime_release_id', 'stale-runtime'),
            ('expected_release_manifest_sha256', '1' * 64),
            ('expected_motion_profile_id', 'stale-profile'),
            ('expected_motion_profile_manifest_sha256', '2' * 64),
            ('expected_motion_profile_runtime_release_id', 'stale-runtime'),
            ('expected_approved_speed_grades', [5, 20]),
            ('expected_bounded_call_artifact_sha256', '3' * 64),
            ('expected_stop_isolation_artifact_sha256', '4' * 64),
            ('expected_hung_command_stop_report_sha256', '5' * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                store, path = create_store(root)
                before = store.snapshot()
                arguments = expected_binding_arguments()
                arguments[key] = value
                with self.assertRaises(GripperSafetyLatchError):
                    PersistentGripperSafetyLatch.open(
                        path, 'session-stale',
                        session_nonce_factory=lambda: 'nonce-stale-session',
                        **arguments
                    )
                self.assertEqual(store.snapshot(), before)

    def test_rehashed_single_binding_field_tamper_stays_fail_closed(self):
        mutations = (
            ('runtime_release_id', 'gripper-runtime-r2'),
            ('release_manifest_sha256', '1' * 64),
            ('motion_profile_id', 'gripper-profile-r2'),
            ('motion_profile_manifest_sha256', '2' * 64),
            ('motion_profile_runtime_release_id', 'gripper-runtime-r2'),
            ('approved_speed_grades', [5, 20]),
            ('bounded_call_artifact_sha256', '3' * 64),
            ('stop_isolation_artifact_sha256', '4' * 64),
            ('hung_command_stop_report_sha256', '5' * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                creator, path = create_store(root)
                creator.latch('physical isolation required')
                restarted = open_store(
                    path, 'session-before-tamper', 'nonce-before-tamper')
                rewrite_generation_chain_binding(path, {key: value})
                with self.assertRaises(GripperSafetyLatchError):
                    restarted.snapshot()
                with self.assertRaises(GripperSafetyLatchError):
                    PersistentGripperSafetyLatch.open(
                        path, 'session-after-tamper',
                        session_nonce_factory=lambda: 'nonce-after-tamper',
                        **expected_binding_arguments()
                    )

    def test_fresh_credential_cannot_bypass_rehashed_binding_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            clearer = open_store(
                path, 'session-clearer', 'nonce-session-clearer')
            credential = clearer.build_clearance_credential(
                'clear-after-tamper', PHYSICAL_HASH, APPROVAL_HASH)
            rewrite_generation_chain_binding(
                path, {'bounded_call_artifact_sha256': '3' * 64})
            validator_calls = []
            with self.assertRaises(GripperSafetyLatchError):
                clearer.clear(
                    credential,
                    approval_validator=lambda *_: validator_calls.append(1))
            self.assertEqual(validator_calls, [])
            latest = max(path.glob('generation-*')) / 'record.json'
            payload = json.loads(latest.read_text(encoding='utf-8'))[
                'payload']
            self.assertEqual(payload['status'], 'ACTIVE')

    def test_execution_artifact_hash_reuse_is_rejected_before_create(self):
        collisions = (
            ('bounded_call_artifact_sha256', RELEASE_HASH),
            ('stop_isolation_artifact_sha256', PROFILE_HASH),
            ('stop_isolation_artifact_sha256', BOUNDED_CALL_HASH),
            ('hung_command_stop_report_sha256', BOUNDED_CALL_HASH),
            ('hung_command_stop_report_sha256', STOP_ISOLATION_HASH),
        )
        for key, value in collisions:
            with self.subTest(key=key, value=value), \
                    tempfile.TemporaryDirectory() as root:
                path = Path(root) / 'gripper-safety-latch'
                arguments = binding_arguments()
                arguments[key] = value
                with self.assertRaisesRegex(
                        GripperSafetyLatchError, 'must be distinct'):
                    PersistentGripperSafetyLatch.create(
                        path, 'session-collision',
                        store_id_factory=lambda: 'store-collision',
                        session_nonce_factory=lambda: 'nonce-collision',
                        **arguments
                    )
                self.assertFalse(path.exists())

    def test_pre_latch_session_cannot_clear_later_latch(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            old = open_store(path, 'session-old', 'nonce-session-old')
            creator.latch('physical isolation required')
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'predates or created'):
                old.build_clearance_credential(
                    'clear-old', PHYSICAL_HASH, APPROVAL_HASH)
            self.assertTrue(old.active)

    def test_latching_session_cannot_clear_its_own_latch(self):
        with tempfile.TemporaryDirectory() as root:
            creator, unused_path = create_store(root)
            creator.latch('physical isolation required')
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'predates or created'):
                creator.build_clearance_credential(
                    'clear-self', PHYSICAL_HASH, APPROVAL_HASH)

    def test_clear_requires_post_latch_session_and_external_exact_true(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            clearer = open_store(path, 'session-new', 'nonce-session-new')
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'external approval validator'):
                clearer.clear(credential)
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'exact True'):
                clearer.clear(credential, approval_validator=lambda *_: 1)
            self.assertTrue(clearer.active)

    def test_valid_fake_clear_is_append_only_and_replay_safe(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            clearer = open_store(path, 'session-new', 'nonce-session-new')
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            before = sorted(item.name for item in path.iterdir())
            cleared = clearer.clear(
                credential, approval_validator=lambda *_: True)
            after = sorted(item.name for item in path.iterdir())
            self.assertEqual(cleared['payload']['status'], 'CLEAR')
            self.assertEqual(cleared['payload']['generation'], 3)
            self.assertEqual(after[:len(before)], before)
            self.assertEqual(len(after), len(before) + 1)
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'no active latch'):
                clearer.clear(credential, approval_validator=lambda *_: True)

    def test_active_relatch_invalidates_late_validator_result(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('first physical isolation requirement')
            clearer = open_store(
                path, 'session-clearer', 'nonce-session-clearer')
            credential = clearer.build_clearance_credential(
                'clear-relatch', PHYSICAL_HASH, APPROVAL_HASH)
            validator_entered = threading.Event()
            release_validator = threading.Event()
            errors = []

            def validator(unused_credential, unused_record):
                validator_entered.set()
                if not release_validator.wait(2.0):
                    raise RuntimeError('test validator release timed out')
                return True

            def clear_late():
                try:
                    clearer.clear(credential, approval_validator=validator)
                except Exception as exc:  # captured for thread assertion
                    errors.append(exc)

            worker = threading.Thread(target=clear_late)
            worker.start()
            self.assertTrue(validator_entered.wait(2.0))
            relatched = creator.latch(
                'new STOP supersedes pending clearance')
            release_validator.set()
            worker.join(2.0)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], GripperSafetyLatchError)
            self.assertIn('stale before commit', str(errors[0]))
            self.assertEqual(relatched['payload']['generation'], 3)
            self.assertEqual(relatched['payload']['status'], 'ACTIVE')
            self.assertEqual(relatched['payload']['clear_after_session_epoch'], 2)
            self.assertEqual(clearer.snapshot(), relatched)

    def test_open_and_latch_share_one_persistent_update_lock(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            original_load = latch_module._load_store
            open_loaded = threading.Event()
            release_open = threading.Event()
            latch_started = threading.Event()
            latch_finished = threading.Event()
            opened = []
            latched = []
            errors = []

            def controlled_load(store_path):
                result = original_load(store_path)
                if threading.current_thread().name == 'open-session':
                    open_loaded.set()
                    if not release_open.wait(2.0):
                        raise RuntimeError('test open release timed out')
                return result

            def issue_session():
                try:
                    opened.append(open_store(
                        path, 'session-race', 'nonce-session-race'))
                except Exception as exc:  # captured for thread assertion
                    errors.append(exc)

            def latch_after_open_load():
                latch_started.set()
                try:
                    latched.append(creator.latch(
                        'concurrent STOP must remain persistent'))
                except Exception as exc:  # captured for thread assertion
                    errors.append(exc)
                finally:
                    latch_finished.set()

            with mock.patch.object(
                    latch_module, '_load_store', side_effect=controlled_load):
                open_worker = threading.Thread(
                    name='open-session', target=issue_session)
                open_worker.start()
                self.assertTrue(open_loaded.wait(2.0))
                latch_worker = threading.Thread(target=latch_after_open_load)
                latch_worker.start()
                try:
                    self.assertTrue(latch_started.wait(2.0))
                    self.assertFalse(latch_finished.wait(0.05))
                finally:
                    release_open.set()
                    open_worker.join(2.0)
                    latch_worker.join(2.0)

            self.assertFalse(open_worker.is_alive())
            self.assertFalse(latch_worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(opened), 1)
            self.assertEqual(len(latched), 1)
            current = opened[0].snapshot()['payload']
            self.assertEqual(current['generation'], 2)
            self.assertEqual(current['status'], 'ACTIVE')
            self.assertEqual(current['last_session_epoch'], 2)
            self.assertEqual(current['clear_after_session_epoch'], 2)

    def test_newer_session_revokes_older_post_latch_clearance(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            old_clearer = open_store(
                path, 'session-old-clearer', 'nonce-old-clearer')
            credential = old_clearer.build_clearance_credential(
                'clear-old-session', PHYSICAL_HASH, APPROVAL_HASH)
            newest = open_store(
                path, 'session-newest', 'nonce-session-newest')
            validator_calls = []
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'only the latest issued'):
                old_clearer.clear(
                    credential,
                    approval_validator=lambda *_: validator_calls.append(1))
            self.assertEqual(validator_calls, [])
            self.assertTrue(newest.active)

    def test_clearance_id_cannot_be_reused_after_a_later_relatch(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('first physical isolation requirement')
            first_clearer = open_store(
                path, 'session-first-clearer', 'nonce-first-clearer')
            first = first_clearer.build_clearance_credential(
                'clearance-replay-id', PHYSICAL_HASH, APPROVAL_HASH)
            first_clearer.clear(first, approval_validator=lambda *_: True)
            first_clearer.latch('second physical isolation requirement')
            newest = open_store(
                path, 'session-second-clearer', 'nonce-second-clearer')
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'already committed'):
                newest.build_clearance_credential(
                    'clearance-replay-id', PHYSICAL_HASH, APPROVAL_HASH)
            forged = newest.build_clearance_credential(
                'clearance-new-id', PHYSICAL_HASH, APPROVAL_HASH)
            forged['clearance_id'] = 'clearance-replay-id'
            validator_calls = []
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'already committed'):
                newest.clear(
                    forged,
                    approval_validator=lambda *_: validator_calls.append(1))
            self.assertEqual(validator_calls, [])
            self.assertTrue(newest.active)

    def test_chain_rejects_clear_by_non_latest_issued_session(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            old_clearer = open_store(
                path, 'session-old-clearer', 'nonce-old-clearer')
            newest = open_store(
                path, 'session-newest', 'nonce-session-newest')
            current = newest.snapshot()
            forged_payload = copy.deepcopy(current['payload'])
            forged_payload.update({
                'generation': forged_payload['generation'] + 1,
                'event': 'CLEARED',
                'status': 'CLEAR',
                'previous_record_sha256': current['record_sha256'],
                'event_session_epoch': old_clearer._session['epoch'],
                'event_session_id': old_clearer._session['session_id'],
                'event_session_nonce': old_clearer._session['nonce'],
                'reason': 'forged stale-session clearance',
                'clearance_id': 'forged-clearance-id',
                'physical_verification_artifact_sha256': PHYSICAL_HASH,
                'approval_artifact_sha256': APPROVAL_HASH,
            })
            forged_record = latch_module._record_from_payload(forged_payload)
            with latch_module._PROCESS_WRITER_LOCK:
                with latch_module._locked_writer(path):
                    transaction = latch_module._publish_generation(
                        path, forged_record)
                latch_module._finish_generation_publication(
                    path, transaction)
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'invalid or replayed'):
                newest.snapshot()

    def test_chain_rejects_initial_clearance_evidence_and_id_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            initial = store.snapshot()
            forged_payload = copy.deepcopy(initial['payload'])
            forged_payload.update({
                'latched_session_epoch': 1,
                'clear_after_session_epoch': 1,
                'clearance_id': 'forged-initial-clearance',
                'physical_verification_artifact_sha256': PHYSICAL_HASH,
                'approval_artifact_sha256': APPROVAL_HASH,
            })
            forged_record = latch_module._record_from_payload(forged_payload)
            record_path = path / 'generation-00000000000000000000' \
                / 'record.json'
            record_path.write_bytes(canonical_json_bytes(forged_record))
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'initial store record'):
                store.snapshot()

    def test_forged_credential_fields_rejected_before_validator(self):
        mutations = (
            ('expected_generation', 2.0),
            ('expected_record_sha256', 'e' * 64),
            ('clear_after_session_epoch', 0),
            ('clearing_session_epoch', 999),
            ('clearing_session_id', 'forged-session'),
            ('clearing_session_nonce', 'forged-session-nonce'),
            ('runtime_release_id', 'stale-runtime'),
            ('release_manifest_sha256', 'f' * 64),
            ('motion_profile_id', 'forged-profile'),
            ('motion_profile_manifest_sha256', '1' * 64),
            ('motion_profile_runtime_release_id', 'stale-runtime'),
            ('approved_speed_grades', [5, 99]),
            ('bounded_call_artifact_sha256', '2' * 64),
            ('stop_isolation_artifact_sha256', '3' * 64),
            ('hung_command_stop_report_sha256', '4' * 64),
            ('authenticity_limit', 'SELF_ASSERTED'),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                creator, path = create_store(root)
                creator.latch('physical isolation required')
                clearer = open_store(
                    path, 'session-new', 'nonce-session-new')
                credential = clearer.build_clearance_credential(
                    'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
                credential[key] = value
                calls = []
                with self.assertRaises(GripperSafetyLatchError):
                    clearer.clear(
                        credential,
                        approval_validator=lambda *_: calls.append(1))
                self.assertEqual(calls, [])
                self.assertTrue(clearer.active)

    def test_record_tamper_and_noncanonical_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            tampered = copy.deepcopy(store.snapshot())
            tampered['payload']['reason'] = 'forged state'
            record_path = path / 'generation-00000000000000000000' \
                / 'record.json'
            record_path.write_bytes(canonical_json_bytes(tampered))
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'SHA-256 mismatch'):
                store.snapshot()

        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            record_path = path / 'generation-00000000000000000000' \
                / 'record.json'
            value = json.loads(record_path.read_text(encoding='utf-8'))
            record_path.write_text(json.dumps(value, indent=2), encoding='utf-8')
            with self.assertRaisesRegex(
                    GripperSafetyLatchError,
                    'not canonical|changed during the bounded read'):
                store.snapshot()

    def test_record_and_writer_lock_hardlinks_fail_closed(self):
        for target_name in ('record', 'writer-lock'):
            with self.subTest(target=target_name), \
                    tempfile.TemporaryDirectory() as root:
                store, path = create_store(root)
                if target_name == 'record':
                    target = path / 'generation-00000000000000000000' \
                        / 'record.json'
                else:
                    target = path / latch_module.WRITER_LOCK_NAME
                alias = Path(root) / '{}-hardlink'.format(target_name)
                try:
                    os.link(str(target), str(alias))
                except (AttributeError, NotImplementedError, OSError):
                    self.skipTest('hardlink creation is unavailable')
                with self.assertRaisesRegex(
                        GripperSafetyLatchError,
                        'exactly one filesystem link'):
                    store.snapshot()

    def test_record_same_bytes_inode_swap_between_lstat_and_open_is_rejected(
            self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            record_path = path / 'generation-00000000000000000000' \
                / 'record.json'
            original_payload = record_path.read_bytes()
            backup = Path(root) / 'record-original-backup'
            original_open = latch_module.os.open
            swapped = {'done': False}

            def controlled_open(raw_path, flags, *args):
                if Path(raw_path) == record_path and not swapped['done']:
                    record_path.replace(backup)
                    record_path.write_bytes(original_payload)
                    swapped['done'] = True
                return original_open(raw_path, flags, *args)

            with mock.patch.object(
                    latch_module.os, 'open', side_effect=controlled_open), \
                    self.assertRaisesRegex(
                        GripperSafetyLatchError, 'identity changed'):
                store.snapshot()
            self.assertTrue(swapped['done'])

    def test_writer_lock_same_bytes_inode_swap_before_open_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            lock_path = path / latch_module.WRITER_LOCK_NAME
            original_payload = lock_path.read_bytes()
            backup = Path(root) / 'writer-lock-original-backup'
            original_open = latch_module.os.open
            swapped = {'done': False}

            def controlled_open(raw_path, flags, *args):
                if Path(raw_path) == lock_path and not swapped['done']:
                    lock_path.replace(backup)
                    lock_path.write_bytes(original_payload)
                    swapped['done'] = True
                return original_open(raw_path, flags, *args)

            with mock.patch.object(
                    latch_module.os, 'open', side_effect=controlled_open), \
                    self.assertRaisesRegex(
                        GripperSafetyLatchError, 'inode changed'):
                store.snapshot()
            self.assertTrue(swapped['done'])

    def test_gap_unknown_entry_and_pending_update_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            (path / '.pending-abandoned').mkdir()
            with self.assertRaisesRegex(
                    GripperSafetyLatchError,
                    'incomplete publication transaction.*BLOCKED'):
                store.snapshot()

        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            current = store.snapshot()
            generation = path / 'generation-00000000000000000002'
            generation.mkdir()
            (generation / 'record.json').write_bytes(
                canonical_json_bytes(current))
            with self.assertRaisesRegex(
                    GripperSafetyLatchError, 'not contiguous'):
                store.snapshot()

    def test_local_hash_chain_does_not_claim_authenticity_or_release(self):
        self.assertIn('EXTERNAL_VALIDATOR_REQUIRED', AUTHENTICITY_LIMIT)
        source = MODULE.read_text(encoding='utf-8').lower()
        self.assertIn('not a\nsignature', source)
        self.assertNotIn('hardware_release_ready = true', source)


if __name__ == '__main__':
    unittest.main()
