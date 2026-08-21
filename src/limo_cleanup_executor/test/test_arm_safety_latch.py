import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import limo_cleanup_executor.arm_safety_latch as latch_module
from limo_cleanup_executor.arm_safety_latch import (
    AUTHENTICITY_LIMIT,
    ArmSafetyLatchError,
    PersistentArmSafetyLatch,
    canonical_json_bytes,
)


ROOT = Path(__file__).parents[1]
MODULE = ROOT / 'limo_cleanup_executor' / 'arm_safety_latch.py'
RUNTIME = 'runtime-release-r1'
RELEASE_HASH = 'a' * 64
PHYSICAL_HASH = 'b' * 64
APPROVAL_HASH = 'c' * 64
PROFILE_ID = 'arm-acceleration-profile-r1'
PROFILE_HASH = 'd' * 64
EXECUTION_SAFETY_HASH = 'e' * 64
APPROVED_SPEED_GRADES = [5, 10]


def binding_arguments():
    return {
        'runtime_release_id': RUNTIME,
        'release_manifest_sha256': RELEASE_HASH,
        'acceleration_profile_id': PROFILE_ID,
        'acceleration_profile_manifest_sha256': PROFILE_HASH,
        'acceleration_profile_runtime_release_id': RUNTIME,
        'approved_speed_grades': list(APPROVED_SPEED_GRADES),
        'bounded_call_artifact_sha256': EXECUTION_SAFETY_HASH,
        'stop_isolation_artifact_sha256': EXECUTION_SAFETY_HASH,
        'hung_command_stop_report_sha256': EXECUTION_SAFETY_HASH,
    }


def open_binding_arguments():
    return {
        'expected_runtime_release_id': RUNTIME,
        'expected_release_manifest_sha256': RELEASE_HASH,
        'expected_acceleration_profile_id': PROFILE_ID,
        'expected_acceleration_profile_manifest_sha256': PROFILE_HASH,
        'expected_acceleration_profile_runtime_release_id': RUNTIME,
        'expected_approved_speed_grades': list(APPROVED_SPEED_GRADES),
        'expected_bounded_call_artifact_sha256': EXECUTION_SAFETY_HASH,
        'expected_stop_isolation_artifact_sha256': EXECUTION_SAFETY_HASH,
        'expected_hung_command_stop_report_sha256': EXECUTION_SAFETY_HASH,
    }


def create_store(root):
    path = Path(root) / 'arm_safety_latch.json'
    store = PersistentArmSafetyLatch.create(
        path,
        store_id_factory=lambda: 'store-001',
        **binding_arguments())
    return store, path


def open_store(path):
    return PersistentArmSafetyLatch.open(path, **open_binding_arguments())


def session_ledger_path(path):
    return path.with_name(path.name + '.sessions')


def read_session_ledger(path):
    return json.loads(session_ledger_path(path).read_text(encoding='utf-8'))


def write_session_ledger(path, ledger):
    session_ledger_path(path).write_bytes(canonical_json_bytes(ledger))


def rehash_session_ledger(ledger):
    ledger['ledger_sha256'] = hashlib.sha256(
        canonical_json_bytes(ledger['payload'])).hexdigest()
    return ledger


def rehash_record(record):
    record['record_sha256'] = hashlib.sha256(
        canonical_json_bytes(record['payload'])).hexdigest()
    return record


def rewrite_arm_binding(path, mutations, targets=('record', 'ledger')):
    """Rewrite selected local binding copies with valid local hashes."""
    if 'record' in targets:
        record = json.loads(path.read_text(encoding='utf-8'))
        record['payload'].update(copy.deepcopy(mutations))
        path.write_bytes(canonical_json_bytes(rehash_record(record)))
    if 'ledger' in targets:
        ledger = read_session_ledger(path)
        ledger['payload'].update(copy.deepcopy(mutations))
        write_session_ledger(path, rehash_session_ledger(ledger))


@contextmanager
def fail_update_context_exit(path, failure_kind):
    """Fail after publication while the commit marker is still present."""
    original_validate = latch_module._validate_opened_path
    original_unlock = latch_module._unlock_descriptor
    pending_path = path.with_name(path.name + '.commit-pending')
    state = {'injected': False}

    def controlled_validate(descriptor, target, label):
        result = original_validate(descriptor, target, label)
        if (
                failure_kind == 'exit-validation'
                and label == 'persistent update lock'
                and pending_path.exists()
                and not state['injected']):
            state['injected'] = True
            raise ArmSafetyLatchError(
                'injected update-lock exit validation failure')
        return result

    def controlled_unlock(descriptor):
        result = original_unlock(descriptor)
        if (
                failure_kind == 'unlock'
                and pending_path.exists()
                and not state['injected']):
            state['injected'] = True
            raise ArmSafetyLatchError(
                'injected update-lock release failure')
        return result

    with mock.patch.object(
            latch_module, '_validate_opened_path',
            side_effect=controlled_validate), mock.patch.object(
                latch_module, '_unlock_descriptor',
                side_effect=controlled_unlock):
        yield
    if not state['injected']:
        raise AssertionError(
            'update context {} failure was not injected'.format(
                failure_kind))


class PersistentArmSafetyLatchTest(unittest.TestCase):
    def test_module_uses_python38_syntax_and_has_no_runtime_imports(self):
        source = MODULE.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(MODULE), feature_version=(3, 8))
        forbidden = {'rclpy', 'serial', 'pymycobot', 'socket'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split('.')[0], forbidden)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or '').split('.')[0], forbidden)

    def test_create_is_exclusive_canonical_and_session_is_ledger_issued(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            first = store.snapshot()
            self.assertEqual(first['payload']['generation'], 0)
            self.assertEqual(first['payload']['status'], 'CLEAR')
            self.assertEqual(path.read_bytes(), canonical_json_bytes(first))
            self.assertEqual(store.session_epoch, 1)
            self.assertRegex(store.session_nonce, r'^[0-9a-f]{32}$')
            ledger_before = session_ledger_path(path).read_bytes()
            with self.assertRaisesRegex(ArmSafetyLatchError, 'already exists'):
                create_store(root)
            self.assertEqual(
                session_ledger_path(path).read_bytes(), ledger_before)
            restarted = open_store(path)
            self.assertEqual(restarted.session_epoch, 2)

    def test_duplicate_create_never_calls_store_id_factory(self):
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            class ActiveFactory:
                def __init__(self):
                    self.bool_calls = 0
                    self.call_calls = 0

                def __bool__(self):
                    self.bool_calls += 1
                    return False

                def __call__(self):
                    self.call_calls += 1
                    return 'must-not-be-used'

            factory = ActiveFactory()

            with self.assertRaisesRegex(ArmSafetyLatchError, 'already exists'):
                PersistentArmSafetyLatch.create(
                    path, store_id_factory=factory,
                    **binding_arguments())
            self.assertEqual(factory.bool_calls, 0)
            self.assertEqual(factory.call_calls, 0)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'arm_safety_latch.json'
            factory = ActiveFactory()
            store = PersistentArmSafetyLatch.create(
                path, store_id_factory=factory,
                **binding_arguments())
            self.assertEqual(factory.bool_calls, 0)
            self.assertEqual(factory.call_calls, 1)
            self.assertEqual(store.snapshot()['payload']['store_id'],
                             'must-not-be-used')

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'arm_safety_latch.json'
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'must be callable'):
                PersistentArmSafetyLatch.create(
                    path, store_id_factory=[],
                    **binding_arguments())
            self.assertFalse(path.exists())

    def test_device_paths_are_rejected_before_filesystem_access(self):
        for value in ('/dev', '/dev/elephant', '/DEV/ttyUSB0', '\\dev\\elephant'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ArmSafetyLatchError, 'device paths are forbidden'):
                PersistentArmSafetyLatch.open(
                    value, **open_binding_arguments())

    def test_active_latch_survives_restart_and_new_session_advances(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            active = store.latch('software STOP could not be verified')
            restarted = open_store(path)
            self.assertTrue(restarted.active)
            self.assertGreater(restarted.session_epoch, store.session_epoch)
            self.assertEqual(
                active['payload']['minimum_clearing_session_epoch'],
                store.session_epoch + 1)

    def test_pre_latch_existing_session_cannot_clear_later_latch(self):
        with tempfile.TemporaryDirectory() as root:
            latcher, path = create_store(root)
            old_session = open_store(path)
            newer_latcher = open_store(path)
            newer_latcher.latch('physical isolation required')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'issued before the latch'):
                old_session.build_clearance_credential(
                    'clear-001', PHYSICAL_HASH, APPROVAL_HASH)

    def test_relatch_advances_generation_and_clear_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            first = store.latch('first physical isolation requirement')
            newer = open_store(path)
            after_session_issue = newer.snapshot()
            second = store.latch('new physical isolation requirement')
            self.assertEqual(
                second['payload']['generation'],
                after_session_issue['payload']['generation'] + 1)
            self.assertEqual(second['payload']['status'], 'ACTIVE')
            self.assertEqual(
                second['payload']['previous_record_sha256'],
                after_session_issue['record_sha256'])
            self.assertEqual(
                second['payload']['minimum_clearing_session_epoch'],
                newer.session_epoch + 1)
            self.assertEqual(
                second['payload']['reason'],
                'new physical isolation requirement')

    def test_relatch_invalidates_clearance_while_validator_is_running(self):
        with tempfile.TemporaryDirectory() as root:
            latcher, path = create_store(root)
            latcher.latch('first physical isolation requirement')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)

            def validator(unused_credential, unused_record):
                latcher.latch('later STOP requires renewed isolation')
                return True

            with self.assertRaisesRegex(ArmSafetyLatchError, 'stale'):
                clearer.clear(credential, approval_validator=validator)
            current = latcher.snapshot()
            self.assertEqual(current['payload']['status'], 'ACTIVE')
            self.assertEqual(
                current['payload']['reason'],
                'later STOP requires renewed isolation')

    def test_only_latest_issued_session_can_build_or_apply_clearance(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            formerly_latest = open_store(path)
            credential = formerly_latest.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            latest = open_store(path)
            calls = []
            with self.assertRaisesRegex(ArmSafetyLatchError, 'latest issued'):
                formerly_latest.build_clearance_credential(
                    'clear-002', PHYSICAL_HASH, APPROVAL_HASH)
            with self.assertRaisesRegex(ArmSafetyLatchError, 'latest issued'):
                formerly_latest.clear(
                    credential,
                    approval_validator=lambda *_: calls.append(True))
            self.assertEqual(calls, [])
            self.assertTrue(latest.active)

    def test_latching_session_cannot_clear_and_post_latch_session_can(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            active = store.latch('physical isolation required')
            with self.assertRaisesRegex(ArmSafetyLatchError, 'issued before'):
                store.build_clearance_credential(
                    'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            restarted = open_store(path)
            credential = restarted.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            self.assertEqual(
                credential['clearing_session_epoch'], restarted.session_epoch)
            self.assertEqual(
                credential['clearing_session_nonce'], restarted.session_nonce)
            cleared = restarted.clear(
                credential, approval_validator=lambda *_: True)
            self.assertEqual(cleared['payload']['status'], 'CLEAR')
            self.assertEqual(cleared['payload']['previous_record_sha256'],
                             credential['expected_record_sha256'])

    def test_clearance_id_cannot_be_reused_after_clear_and_relatch(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('first physical isolation requirement')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            clearer.clear(credential, approval_validator=lambda *_: True)
            clearer.latch('second physical isolation requirement')
            latest = open_store(path)
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'already consumed'):
                latest.build_clearance_credential(
                    'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            self.assertTrue(latest.active)

    def test_clearance_id_is_consumed_before_record_commit(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            original_replace = latch_module._atomic_replace

            def fail_record_replace(target, payload, token, label):
                if Path(target) == path:
                    raise ArmSafetyLatchError(
                        'injected record publication failure')
                return original_replace(target, payload, token, label)

            with mock.patch.object(
                    latch_module, '_atomic_replace',
                    side_effect=fail_record_replace):
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'injected record'):
                    clearer.clear(
                        credential, approval_validator=lambda *_: True)
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'ACTIVE')
            ledger = read_session_ledger(path)
            self.assertIn(
                'clear-001', ledger['payload']['used_clearance_ids'])
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'commit outcome is uncertain'):
                clearer.snapshot()

    def test_ledger_publication_failure_never_publishes_clear(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            ledger_path = session_ledger_path(path)
            ledger_before = ledger_path.read_bytes()
            original_replace = latch_module._atomic_replace

            def fail_ledger_replace(target, payload, token, label):
                if Path(target) == ledger_path:
                    raise ArmSafetyLatchError(
                        'injected ledger publication failure')
                return original_replace(target, payload, token, label)

            with mock.patch.object(
                    latch_module, '_atomic_replace',
                    side_effect=fail_ledger_replace):
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'injected ledger'):
                    clearer.clear(
                        credential, approval_validator=lambda *_: True)
            self.assertEqual(ledger_path.read_bytes(), ledger_before)
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'ACTIVE')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'commit outcome is uncertain'):
                clearer.snapshot()

    def test_post_publication_fsync_failure_keeps_clear_api_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            original_fsync_directory = latch_module._fsync_directory
            calls = []

            def fail_after_record_publication(directory):
                calls.append(Path(directory))
                if len(calls) == 3:
                    raise OSError('injected final directory fsync failure')
                return original_fsync_directory(directory)

            with mock.patch.object(
                    latch_module, '_fsync_directory',
                    side_effect=fail_after_record_publication):
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'atomic update failed'):
                    clearer.clear(
                        credential, approval_validator=lambda *_: True)
            self.assertEqual(len(calls), 3)
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'CLEAR')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'commit outcome is uncertain'):
                clearer.snapshot()
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'commit outcome is uncertain'):
                    open_store(path)

    def test_update_context_exit_failure_keeps_publication_blocked(self):
        for failure_kind in ('exit-validation', 'unlock'):
            for operation in ('create', 'latch', 'clear'):
                with self.subTest(
                        failure_kind=failure_kind, operation=operation), \
                        tempfile.TemporaryDirectory() as root:
                    path = Path(root) / 'arm_safety_latch.json'
                    if operation == 'create':
                        with fail_update_context_exit(path, failure_kind), \
                                self.assertRaisesRegex(
                                    ArmSafetyLatchError, 'injected update-lock'):
                            create_store(root)
                    else:
                        creator, path = create_store(root)
                        if operation == 'latch':
                            with fail_update_context_exit(
                                    path, failure_kind), \
                                    self.assertRaisesRegex(
                                        ArmSafetyLatchError,
                                        'injected update-lock'):
                                creator.latch(
                                    'update context exit is unverified')
                        else:
                            creator.latch('physical isolation required')
                            clearer = open_store(path)
                            credential = clearer.build_clearance_credential(
                                'clear-update-exit',
                                PHYSICAL_HASH, APPROVAL_HASH)
                            with fail_update_context_exit(
                                    path, failure_kind), \
                                    self.assertRaisesRegex(
                                        ArmSafetyLatchError,
                                        'injected update-lock'):
                                clearer.clear(
                                    credential,
                                    approval_validator=lambda *_: True)
                            raw_record = json.loads(
                                path.read_text(encoding='utf-8'))
                            self.assertEqual(
                                raw_record['payload']['status'], 'CLEAR')
                    self.assertTrue(
                        path.with_name(
                            path.name + '.commit-pending').exists())
                    with self.assertRaisesRegex(
                            ArmSafetyLatchError,
                            'commit outcome is uncertain'):
                        open_store(path)

    def test_post_marker_removal_fsync_failure_returns_committed_clear(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            original_fsync_directory = latch_module._fsync_directory
            calls = []

            def fail_after_marker_removal(directory):
                calls.append(Path(directory))
                if len(calls) == 4:
                    raise OSError(
                        'injected post-commit marker directory fsync failure')
                return original_fsync_directory(directory)

            with mock.patch.object(
                    latch_module, '_fsync_directory',
                    side_effect=fail_after_marker_removal):
                cleared = clearer.clear(
                    credential, approval_validator=lambda *_: True)
            self.assertEqual(len(calls), 4)
            self.assertEqual(cleared['payload']['status'], 'CLEAR')
            self.assertEqual(clearer.snapshot()['payload']['status'], 'CLEAR')
            self.assertFalse(
                path.with_name(path.name + '.commit-pending').exists())

    def test_post_publication_create_fsync_failure_cannot_reopen_store(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'arm_safety_latch.json'
            original_fsync_directory = latch_module._fsync_directory
            calls = []

            def fail_final_create_fsync(directory):
                calls.append(Path(directory))
                if len(calls) == 3:
                    raise OSError('injected create directory fsync failure')
                return original_fsync_directory(directory)

            with mock.patch.object(
                    latch_module, '_fsync_directory',
                    side_effect=fail_final_create_fsync):
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'update lock operation failed'):
                    PersistentArmSafetyLatch.create(
                        path, store_id_factory=lambda: 'store-001',
                        **binding_arguments())
            self.assertEqual(len(calls), 3)
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'CLEAR')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'commit outcome is uncertain'):
                open_store(path)

    def test_clear_requires_external_validator_exact_true_and_replay_fails(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            restarted = open_store(path)
            credential = restarted.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            with self.assertRaisesRegex(ArmSafetyLatchError, 'validator'):
                restarted.clear(credential)
            with self.assertRaisesRegex(ArmSafetyLatchError, 'exact True'):
                restarted.clear(credential, approval_validator=lambda *_: 1)
            restarted.clear(credential, approval_validator=lambda *_: True)
            with self.assertRaisesRegex(ArmSafetyLatchError, 'no active'):
                restarted.clear(credential, approval_validator=lambda *_: True)

    def test_forged_exact_binding_fields_are_rejected_before_validator(self):
        mutations = (
            ('store_id', 'forged-store'),
            ('expected_generation', 99),
            ('expected_record_sha256', 'd' * 64),
            ('latched_session_epoch', 999),
            ('latched_session_nonce', 'forged-latch-nonce'),
            ('minimum_clearing_session_epoch', 999),
            ('clearing_session_epoch', 999),
            ('clearing_session_nonce', 'forged-clear-nonce'),
            ('runtime_release_id', 'stale-release'),
            ('release_manifest_sha256', 'e' * 64),
            ('acceleration_profile_id', 'forged-profile'),
            ('acceleration_profile_manifest_sha256', '1' * 64),
            ('acceleration_profile_runtime_release_id', 'stale-release'),
            ('approved_speed_grades', [5, 99]),
            ('bounded_call_artifact_sha256', '2' * 64),
            ('stop_isolation_artifact_sha256', '3' * 64),
            ('hung_command_stop_report_sha256', '4' * 64),
            ('authenticity_limit', 'SELF_ASSERTED'),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                store, path = create_store(root)
                store.latch('physical isolation required')
                restarted = open_store(path)
                credential = restarted.build_clearance_credential(
                    'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
                credential[key] = value
                calls = []
                with self.assertRaises(ArmSafetyLatchError):
                    restarted.clear(
                        credential,
                        approval_validator=lambda *_: calls.append(True))
                self.assertEqual(calls, [])
                self.assertTrue(restarted.active)

    def test_open_requires_exact_full_release_profile_execution_binding(self):
        mutations = (
            ('expected_runtime_release_id', 'stale-runtime'),
            ('expected_release_manifest_sha256', '1' * 64),
            ('expected_acceleration_profile_id', 'stale-profile'),
            ('expected_acceleration_profile_manifest_sha256', '2' * 64),
            ('expected_acceleration_profile_runtime_release_id',
             'stale-runtime'),
            ('expected_approved_speed_grades', [5, 20]),
            ('expected_bounded_call_artifact_sha256', '3' * 64),
            ('expected_stop_isolation_artifact_sha256', '4' * 64),
            ('expected_hung_command_stop_report_sha256', '5' * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                unused_store, path = create_store(root)
                ledger_before = session_ledger_path(path).read_bytes()
                record_before = path.read_bytes()
                arguments = open_binding_arguments()
                arguments[key] = value
                with self.assertRaises(ArmSafetyLatchError):
                    PersistentArmSafetyLatch.open(path, **arguments)
                self.assertEqual(
                    session_ledger_path(path).read_bytes(), ledger_before)
                self.assertEqual(path.read_bytes(), record_before)

    def test_combined_execution_artifact_keeps_three_explicit_bindings(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            restarted = open_store(path)
            snapshot = restarted.snapshot()['payload']
            ledger = read_session_ledger(path)['payload']
            credential = restarted.build_clearance_credential(
                'clear-combined-artifact', PHYSICAL_HASH, APPROVAL_HASH)
            execution_fields = (
                'bounded_call_artifact_sha256',
                'stop_isolation_artifact_sha256',
                'hung_command_stop_report_sha256',
            )
            self.assertEqual(
                {snapshot[key] for key in execution_fields},
                {EXECUTION_SAFETY_HASH})
            for key in execution_fields:
                self.assertIn(key, snapshot)
                self.assertEqual(snapshot[key], EXECUTION_SAFETY_HASH)
                self.assertEqual(ledger[key], EXECUTION_SAFETY_HASH)
                self.assertEqual(credential[key], EXECUTION_SAFETY_HASH)
            for key, value in binding_arguments().items():
                self.assertEqual(snapshot[key], value)
                self.assertEqual(ledger[key], value)

    def test_combined_execution_artifact_cannot_reuse_release_or_profile(self):
        collisions = (
            ('bounded_call_artifact_sha256', RELEASE_HASH),
            ('stop_isolation_artifact_sha256', PROFILE_HASH),
            ('hung_command_stop_report_sha256', RELEASE_HASH),
        )
        for key, value in collisions:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as root:
                path = Path(root) / 'arm_safety_latch.json'
                arguments = binding_arguments()
                arguments[key] = value
                with self.assertRaisesRegex(
                        ArmSafetyLatchError,
                        'distinct from release.*profile artifacts'):
                    PersistentArmSafetyLatch.create(
                        path, store_id_factory=lambda: 'store-collision',
                        **arguments
                    )
                self.assertFalse(path.exists())

    def test_rehashed_single_binding_field_tamper_stays_fail_closed(self):
        mutations = (
            ('runtime_release_id', 'runtime-release-r2'),
            ('release_manifest_sha256', '1' * 64),
            ('acceleration_profile_id', 'arm-acceleration-profile-r2'),
            ('acceleration_profile_manifest_sha256', '2' * 64),
            ('acceleration_profile_runtime_release_id',
             'runtime-release-r2'),
            ('approved_speed_grades', [5, 20]),
            ('bounded_call_artifact_sha256', '3' * 64),
            ('stop_isolation_artifact_sha256', '4' * 64),
            ('hung_command_stop_report_sha256', '5' * 64),
        )
        for target in ('record', 'ledger'):
            for key, value in mutations:
                with self.subTest(target=target, key=key), \
                        tempfile.TemporaryDirectory() as root:
                    store, path = create_store(root)
                    store.latch('physical isolation required')
                    restarted = open_store(path)
                    rewrite_arm_binding(path, {key: value}, (target,))
                    with self.assertRaises(ArmSafetyLatchError):
                        restarted.snapshot()
                    with self.assertRaises(ArmSafetyLatchError):
                        open_store(path)

    def test_fresh_credential_cannot_bypass_rehashed_binding_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            creator, path = create_store(root)
            creator.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-after-tamper', PHYSICAL_HASH, APPROVAL_HASH)
            rewrite_arm_binding(
                path, {'bounded_call_artifact_sha256': '3' * 64})
            validator_calls = []
            with self.assertRaises(ArmSafetyLatchError):
                clearer.clear(
                    credential,
                    approval_validator=lambda *_: validator_calls.append(1))
            self.assertEqual(validator_calls, [])
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'ACTIVE')

    def test_empty_or_malformed_ledger_fails_closed_without_reinitializing(self):
        corruptions = (
            b'',
            canonical_json_bytes({'schema_version': 2}),
        )
        for corruption in corruptions:
            with self.subTest(corruption=corruption), \
                    tempfile.TemporaryDirectory() as root:
                unused_store, path = create_store(root)
                session_ledger_path(path).write_bytes(corruption)
                with self.assertRaisesRegex(
                        ArmSafetyLatchError, 'ledger is invalid'):
                    open_store(path)
                self.assertEqual(
                    session_ledger_path(path).read_bytes(), corruption)

    def test_orphaned_ledger_forbids_store_recreation(self):
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            ledger_before = session_ledger_path(path).read_bytes()
            path.unlink()
            with self.assertRaisesRegex(ArmSafetyLatchError, 'orphaned'):
                create_store(root)
            self.assertEqual(
                session_ledger_path(path).read_bytes(), ledger_before)

    def test_rehashed_stale_ledger_cannot_restore_superseded_session(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            formerly_latest = open_store(path)
            credential = formerly_latest.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            latest = open_store(path)
            self.assertGreater(
                latest.session_epoch, formerly_latest.session_epoch)
            ledger = read_session_ledger(path)
            removed = ledger['payload']['issued_sessions'].pop()
            self.assertEqual(removed['epoch'], latest.session_epoch)
            previous = ledger['payload']['issued_sessions'][-1]
            ledger['payload']['last_session_epoch'] = previous['epoch']
            ledger['payload']['last_session_nonce'] = previous['nonce']
            write_session_ledger(path, rehash_session_ledger(ledger))
            calls = []
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'anchor|absent'):
                formerly_latest.clear(
                    credential,
                    approval_validator=lambda *_: calls.append(True))
            self.assertEqual(calls, [])
            raw_record = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw_record['payload']['status'], 'ACTIVE')

    def test_forged_ledger_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            ledger = read_session_ledger(path)
            ledger['payload']['used_clearance_ids'] = ['forged-clearance']
            write_session_ledger(path, ledger)
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'ledger is invalid'):
                open_store(path)

    def test_rehashed_clearance_registry_rollback_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            clearer.clear(credential, approval_validator=lambda *_: True)
            ledger = read_session_ledger(path)
            ledger['payload']['used_clearance_ids'] = []
            write_session_ledger(path, rehash_session_ledger(ledger))
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'registry mismatch'):
                clearer.snapshot()

    def test_real_process_restart_preserves_active_and_advances_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required across restart')
            script = (
                'import json,sys; '
                'from limo_cleanup_executor.arm_safety_latch import '
                'PersistentArmSafetyLatch; '
                's=PersistentArmSafetyLatch.open('
                'sys.argv[1],**json.loads(sys.argv[2])); '
                'print(json.dumps({"active":s.active,"epoch":s.session_epoch}))'
            )
            environment = os.environ.copy()
            result = subprocess.run(
                [sys.executable, '-c', script, str(path),
                 json.dumps(open_binding_arguments(), sort_keys=True)],
                check=True, capture_output=True, text=True,
                env=environment, timeout=30)
            child = json.loads(result.stdout.strip())
            self.assertTrue(child['active'])
            self.assertGreater(child['epoch'], store.session_epoch)
            restarted = open_store(path)
            self.assertTrue(restarted.active)
            self.assertGreater(restarted.session_epoch, child['epoch'])

    def test_record_tampering_and_noncanonical_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            active = store.latch('physical isolation required')
            tampered = copy.deepcopy(active)
            tampered['payload']['reason'] = 'forged clear text'
            path.write_bytes(canonical_json_bytes(tampered))
            with self.assertRaisesRegex(ArmSafetyLatchError, 'SHA-256 mismatch'):
                open_store(path)
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            value = json.loads(path.read_text(encoding='utf-8'))
            path.write_text(json.dumps(value, indent=2), encoding='utf-8')
            with self.assertRaisesRegex(ArmSafetyLatchError, 'not canonical'):
                open_store(path)

    def test_self_hashed_impossible_record_shapes_fail_closed(self):
        mutations = (
            ('initial previous hash', lambda record: record['payload'].update({
                'previous_record_sha256': 'd' * 64})),
            ('empty reason', lambda record: record['payload'].update({
                'reason': ''})),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), \
                    tempfile.TemporaryDirectory() as root:
                unused_store, path = create_store(root)
                record = json.loads(path.read_text(encoding='utf-8'))
                mutate(record)
                path.write_bytes(canonical_json_bytes(rehash_record(record)))
                with self.assertRaises(ArmSafetyLatchError):
                    open_store(path)

        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            clearer = open_store(path)
            credential = clearer.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            clearer.clear(credential, approval_validator=lambda *_: True)
            record = json.loads(path.read_text(encoding='utf-8'))
            record['payload']['latched_session_epoch'] = None
            record['payload']['latched_session_nonce'] = None
            record['payload']['minimum_clearing_session_epoch'] = None
            path.write_bytes(canonical_json_bytes(rehash_record(record)))
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'latching session'):
                clearer.snapshot()

    def test_update_lock_is_persistent_and_never_unlinked(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            store.latch('physical isolation required')
            lock_path = path.with_name(path.name + '.update-lock')
            self.assertTrue(lock_path.exists())
            restarted = open_store(path)
            credential = restarted.build_clearance_credential(
                'clear-001', PHYSICAL_HASH, APPROVAL_HASH)
            restarted.clear(credential, approval_validator=lambda *_: True)
            self.assertTrue(lock_path.exists())

    def test_sidecars_require_regular_single_link_files_and_valid_marker(self):
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            lock_path = path.with_name(path.name + '.update-lock')
            lock_path.write_bytes(b'forged-lock-marker\n')
            with self.assertRaisesRegex(ArmSafetyLatchError, 'marker'):
                open_store(path)
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            ledger_path = session_ledger_path(path)
            ledger_path.unlink()
            ledger_path.mkdir()
            with self.assertRaisesRegex(ArmSafetyLatchError, 'ordinary file'):
                open_store(path)
        with tempfile.TemporaryDirectory() as root:
            unused_store, path = create_store(root)
            ledger_path = session_ledger_path(path)
            alias = ledger_path.with_name('ledger-hardlink')
            try:
                os.link(str(ledger_path), str(alias))
            except (OSError, NotImplementedError):
                self.skipTest('hard links unavailable')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, 'exactly one'):
                open_store(path)

    def test_sidecar_source_has_no_follow_reparse_and_inode_checks(self):
        source = MODULE.read_text(encoding='utf-8')
        self.assertIn('O_NOFOLLOW', source)
        self.assertIn('FILE_ATTRIBUTE_REPARSE_POINT', source)
        self.assertIn('os.lstat', source)
        self.assertIn('os.fstat', source)
        self.assertIn('path/inode identity changed', source)

    def test_ancestor_symlink_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            real = root_path / 'real'
            alias = root_path / 'alias'
            real.mkdir()
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('directory symlinks unavailable')
            with self.assertRaisesRegex(ArmSafetyLatchError, 'symbolic links'):
                PersistentArmSafetyLatch.create(
                    alias / 'latch.json', **binding_arguments())

    def test_final_symlink_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store, path = create_store(root)
            target = path.with_name('target.json')
            path.replace(target)
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('file symlinks unavailable')
            with self.assertRaisesRegex(
                    ArmSafetyLatchError, r'symbolic(?:-| )links?'):
                open_store(path)

    def test_hashes_are_integrity_only_not_authenticity_claims(self):
        self.assertIn('EXTERNAL_VALIDATOR_REQUIRED', AUTHENTICITY_LIMIT)
        source = MODULE.read_text(encoding='utf-8').lower()
        self.assertIn('not authenticity', source)


if __name__ == '__main__':
    unittest.main()
