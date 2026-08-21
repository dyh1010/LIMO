import threading

import pytest

from limo_cleanup_executor.gripper_gateway_core import (
    GripperGatewayCore,
    GripperGatewayError,
    GripperGatewayPolicy,
    GripperGatewayState,
    GripperMotionRejected,
)


REVIEWED_TOOL_MODEL = 'FINAL_TOOL_MODEL'
REVIEWED_TOOL_REVISION = 'FINAL_TOOL_REV_A'
REVIEWED_CONTROLLER_IDENTITY = 'FINAL_CONTROLLER_A'
REVIEWED_TRANSPORT_IDENTITY = 'FINAL_TRANSPORT_A'
REVIEWED_PROTOCOL_IDENTITY = 'FINAL_PROTOCOL_A'
CONTROLLER_BOOT_ID = 'BOOT_A'
TOOL_REVISION = REVIEWED_TOOL_REVISION


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeBackend:
    SAFETY_CAPABILITIES = {
        'execution_mode': 'PURE_FAKE',
        'bounded_calls_enforced': True,
        'native_deadline_enforced': True,
        'method_deadlines_s': {
            'read_state': 1.0,
            'command_position': 1.0,
            'stop': 1.0,
            'close': 1.0,
        },
        'independent_stop_channel': True,
        'native_cancel_enforced': True,
        'independent_stop_lock_domain': True,
        'stop_not_queued_behind_commands': True,
        'release_binding': None,
        'persistent_latch_binding': None,
    }

    def __init__(self):
        self.sequence = 0
        self.sample_timestamp = 0.0
        self.connected = True
        self.valid = True
        self.enabled = True
        self.moving = False
        self.position = 1.0
        self.fault_code = 0
        self.tool_model = REVIEWED_TOOL_MODEL
        self.tool_revision = REVIEWED_TOOL_REVISION
        self.controller_identity = REVIEWED_CONTROLLER_IDENTITY
        self.transport_identity = REVIEWED_TRANSPORT_IDENTITY
        self.protocol_identity = REVIEWED_PROTOCOL_IDENTITY
        self.controller_boot_id = CONTROLLER_BOOT_ID
        self.commands = []
        self.stop_calls = 0
        self.closed = False
        self.close_count = 0
        self.fail_command = False
        self.fail_stop = False
        self.fail_read = False
        self.fail_close = False
        self.reported_command_id = ''
        self.auto_increment_sequence = True
        self.auto_increment_timestamp = True
        self.omitted_fields = set()

    def read_state(self):
        if self.fail_read:
            raise RuntimeError('state transport failed')
        if self.auto_increment_sequence:
            self.sequence += 1
        if self.auto_increment_timestamp:
            self.sample_timestamp += 0.01
        sample = {
            'sequence': self.sequence,
            'sample_timestamp': self.sample_timestamp,
            'command_id': self.reported_command_id,
            'tool_model': self.tool_model,
            'tool_revision': self.tool_revision,
            'controller_identity': self.controller_identity,
            'transport_identity': self.transport_identity,
            'protocol_identity': self.protocol_identity,
            'controller_boot_id': self.controller_boot_id,
            'connected': self.connected,
            'valid': self.valid,
            'enabled': self.enabled,
            'moving': self.moving,
            'position': self.position,
            'fault_code': self.fault_code,
        }
        return {
            name: value for name, value in sample.items()
            if name not in self.omitted_fields
        }

    def command_position(self, position, speed, command_id):
        self.commands.append((position, speed, command_id))
        self.reported_command_id = command_id
        self.moving = True
        if self.fail_command:
            raise RuntimeError('driver failed after accepting command')

    def stop(self):
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError('stop transport failed')
        self.moving = False

    def close(self):
        self.close_count += 1
        if self.fail_close:
            raise RuntimeError('close transport failed')
        self.closed = True


def make_policy(**overrides):
    values = {
        'permit_motion': True,
        'reviewed_tool_model': REVIEWED_TOOL_MODEL,
        'reviewed_tool_revision': REVIEWED_TOOL_REVISION,
        'reviewed_controller_identity': REVIEWED_CONTROLLER_IDENTITY,
        'reviewed_transport_identity': REVIEWED_TRANSPORT_IDENTITY,
        'reviewed_protocol_identity': REVIEWED_PROTOCOL_IDENTITY,
        'state_max_age_s': 0.5,
        'command_timeout_s': 1.0,
        'stop_timeout_s': 0.5,
        'stable_samples_required': 2,
        'position_tolerance': 0.02,
        'stationary_position_tolerance': 0.01,
        'stationary_dwell_s': 0.2,
    }
    values.update(overrides)
    return GripperGatewayPolicy(**values)


def make_core(
        permit_motion=True,
        stable_samples=2,
        stationary_dwell_s=0.2,
        stationary_position_tolerance=0.01,
        command_id_factory=None):
    clock = FakeClock()
    backend = FakeBackend()
    policy = make_policy(
        permit_motion=permit_motion,
        stable_samples_required=stable_samples,
        stationary_position_tolerance=stationary_position_tolerance,
        stationary_dwell_s=stationary_dwell_s,
    )
    allowed = {
        'motion': {'AUTH', 'MOVE_AUTH', 'SECOND_MOVE_AUTH'},
        'ack': {'HUMAN_ACK', 'ACK', 'ACK_AUTH', 'SECOND_ACK_AUTH'},
    }

    def validate_authorization(value, purpose, unused_session_id):
        return value in allowed[purpose]

    core = GripperGatewayCore(
        backend,
        policy,
        clock=clock,
        authorization_validator=validate_authorization,
        command_id_factory=command_id_factory,
    )
    return core, backend, clock


IDENTITY_POLICY_FIELDS = (
    'reviewed_tool_model',
    'reviewed_tool_revision',
    'reviewed_controller_identity',
    'reviewed_transport_identity',
    'reviewed_protocol_identity',
)

SNAPSHOT_IDENTITY_FIELDS = (
    'tool_model',
    'tool_revision',
    'controller_identity',
    'transport_identity',
    'protocol_identity',
)


@pytest.mark.parametrize('field,invalid', [
    (field, invalid)
    for field in IDENTITY_POLICY_FIELDS
    for invalid in ('', ' surrounded ', None)
])
def test_policy_rejects_unreviewed_identity(field, invalid):
    policy = make_policy(**{field: invalid})
    with pytest.raises(ValueError, match=field):
        policy.validate()


def test_core_rejects_policy_subclass_before_overridden_validation():
    class PolicySubclass(GripperGatewayPolicy):
        def validate(self):
            raise AssertionError('subclass validate must never execute')

    policy = PolicySubclass(**make_policy().__dict__)
    with pytest.raises(ValueError, match='exact GripperGatewayPolicy'):
        GripperGatewayCore(FakeBackend(), policy, clock=FakeClock())


def test_core_keeps_an_exact_immutable_policy_snapshot():
    policy = make_policy()
    core = GripperGatewayCore(FakeBackend(), policy, clock=FakeClock())
    assert type(core._policy) is GripperGatewayPolicy
    assert core._policy is not policy
    assert core._policy == policy


def test_constructor_does_not_evaluate_clock_or_factory_truthiness():
    class ActiveCallable:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        def __bool__(self):
            raise AssertionError('truthiness must not be evaluated')

        def __call__(self):
            self.calls += 1
            return self.value

    clock = ActiveCallable(0.0)
    command_id_factory = ActiveCallable('COMMAND-ID')
    core = GripperGatewayCore(
        FakeBackend(),
        make_policy(),
        clock=clock,
        command_id_factory=command_id_factory,
    )
    assert core._clock is clock
    assert core._command_id_factory is command_id_factory
    assert command_id_factory.calls == 0


def test_exact_reviewed_identity_is_required_before_ready():
    core, backend, unused_clock = make_core()
    snapshot = core.refresh()
    assert core.state == GripperGatewayState.READY
    assert snapshot.tool_model == REVIEWED_TOOL_MODEL
    assert snapshot.tool_revision == REVIEWED_TOOL_REVISION
    assert snapshot.controller_identity == REVIEWED_CONTROLLER_IDENTITY
    assert snapshot.transport_identity == REVIEWED_TRANSPORT_IDENTITY
    assert snapshot.protocol_identity == REVIEWED_PROTOCOL_IDENTITY
    assert snapshot.controller_boot_id == CONTROLLER_BOOT_ID
    assert backend.commands == []


@pytest.mark.parametrize('field', SNAPSHOT_IDENTITY_FIELDS)
def test_feedback_identity_mismatch_permanently_locks_process(field):
    core, backend, unused_clock = make_core()
    setattr(backend, field, 'UNREVIEWED_VALUE')
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._identity_lockout is True
    assert backend.commands == []

    setattr(backend, field, globals()['REVIEWED_' + field.upper()])
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='new gateway process'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperMotionRejected, match='new gateway process'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert backend.commands == []


@pytest.mark.parametrize('field,mode', [
    (field, mode)
    for field in SNAPSHOT_IDENTITY_FIELDS + ('controller_boot_id',)
    for mode in ('missing', 'empty', 'whitespace', 'type')
])
def test_invalid_feedback_identity_permanently_locks_process(field, mode):
    core, backend, unused_clock = make_core()
    if mode == 'missing':
        backend.omitted_fields.add(field)
    elif mode == 'empty':
        setattr(backend, field, '')
    elif mode == 'whitespace':
        setattr(backend, field, ' identity ')
    else:
        setattr(backend, field, 7)

    with pytest.raises(GripperGatewayError, match='identity validation failed'):
        core.refresh()
    assert core._identity_lockout is True
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert backend.commands == []

    backend.omitted_fields.discard(field)
    defaults = {
        'tool_model': REVIEWED_TOOL_MODEL,
        'tool_revision': REVIEWED_TOOL_REVISION,
        'controller_identity': REVIEWED_CONTROLLER_IDENTITY,
        'transport_identity': REVIEWED_TRANSPORT_IDENTITY,
        'protocol_identity': REVIEWED_PROTOCOL_IDENTITY,
        'controller_boot_id': CONTROLLER_BOOT_ID,
    }
    setattr(backend, field, defaults[field])
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='new gateway process'):
        core.acknowledge_local_fault('ACK', core.session_id)


def test_controller_boot_change_while_ready_permanently_locks_without_stop():
    core, backend, unused_clock = make_core()
    core.refresh()
    backend.controller_boot_id = 'BOOT_B'
    core.refresh()
    assert core._identity_lockout is True
    assert core.physical_stop_required is False
    assert backend.stop_calls == 0
    assert backend.commands == []

    backend.controller_boot_id = CONTROLLER_BOOT_ID
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='new gateway process'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert backend.commands == []


@pytest.mark.parametrize('drift_field', [
    'controller_boot_id', 'controller_identity',
])
def test_identity_drift_during_execution_stops_once_and_requires_physical(
        drift_field):
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    setattr(backend, drift_field, 'DRIFTED_VALUE')
    core.refresh()
    assert core._identity_lockout is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1

    core.refresh()
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id,
            TOOL_REVISION)
    assert backend.stop_calls == 1
    assert len(backend.commands) == 1


def test_identity_drift_stop_failure_is_attempted_once():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.fail_stop = True
    backend.controller_boot_id = 'BOOT_B'
    core.refresh()
    assert core._identity_lockout is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    core.refresh()
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    assert backend.close_count == 1


def test_new_process_rejects_old_session_and_session_bound_authorization():
    old_core, unused_backend, unused_clock = make_core()
    old_session = old_core.session_id
    validator_calls = []

    def old_session_validator(value, purpose, session_id):
        validator_calls.append((value, purpose, session_id))
        return session_id == old_session

    new_backend = FakeBackend()
    new_core = GripperGatewayCore(
        new_backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=old_session_validator,
    )
    new_core.refresh()
    assert new_core.session_id != old_session
    with pytest.raises(GripperMotionRejected, match='session'):
        new_core.command_position(
            0.2, 0.2, 'AUTH', old_session, TOOL_REVISION)
    assert validator_calls == []
    with pytest.raises(GripperMotionRejected, match='session'):
        new_core.request_stop('stale process stop', old_session)
    with pytest.raises(GripperMotionRejected, match='session'):
        new_core.acknowledge_local_fault('ACK', old_session)
    assert new_backend.stop_calls == 0
    with pytest.raises(GripperMotionRejected, match='does not match motion'):
        new_core.command_position(
            0.2, 0.2, 'AUTH', new_core.session_id, TOOL_REVISION)
    assert validator_calls == [('AUTH', 'motion', new_core.session_id)]
    assert new_backend.commands == []


def test_wrong_tool_revision_has_no_authorization_or_command_side_effects():
    validator_calls = []
    factory_calls = []

    def validator(value, purpose, session_id):
        validator_calls.append((value, purpose, session_id))
        return True

    def command_id_factory():
        factory_calls.append(True)
        return 'COMMAND'

    backend = FakeBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=validator,
        command_id_factory=command_id_factory,
    )
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='tool_revision'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, 'WRONG_REVISION')
    assert validator_calls == []
    assert factory_calls == []
    assert core._used_authorization_ids == set()
    assert core._issued_command_ids == set()
    assert backend.commands == []


def test_backend_failure_occurs_after_authorization_and_command_id_consumed():
    events = []

    def validator(value, purpose, session_id):
        events.append(('authorization', value, purpose, session_id))
        return True

    def command_id_factory():
        events.append(('command_id',))
        return 'ORDERED_COMMAND'

    class OrderedBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            events.append((
                'backend',
                command_id,
                command_id in core._issued_command_ids,
                'AUTH' in core._used_authorization_ids,
            ))
            super().command_position(position, speed, command_id)

    backend = OrderedBackend()
    backend.fail_command = True
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=validator,
        command_id_factory=command_id_factory,
    )
    core.refresh()
    with pytest.raises(GripperGatewayError, match='command send failed'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert events[0][0] == 'authorization'
    assert events[1] == ('command_id',)
    assert events[2] == ('backend', 'ORDERED_COMMAND', True, True)
    assert backend.stop_calls == 1


def test_validator_cannot_reenter_close_and_revive_old_command():
    backend = FakeBackend()
    validator_errors = []
    core = None

    def validator(value, purpose, session_id):
        try:
            core.close()
        except Exception as error:
            validator_errors.append(error)
        else:
            raise AssertionError('reentrant close must be rejected')
        return True

    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=validator,
    )
    core.refresh()
    command = core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert command.command_id
    assert len(validator_errors) == 1
    assert isinstance(validator_errors[0], GripperGatewayError)
    assert 'reentrant gateway close is prohibited' in str(
        validator_errors[0])
    assert backend.close_count == 0
    assert len(backend.commands) == 1
    assert core.state == GripperGatewayState.EXECUTING


def test_backend_callback_cannot_reenter_stop_or_close():
    reentry_errors = []
    core = None

    class ReentrantBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            for operation in (
                    lambda: core.request_stop('reentrant', core.session_id),
                    core.close):
                try:
                    operation()
                except Exception as error:
                    reentry_errors.append(error)
                else:
                    raise AssertionError('backend reentry must be rejected')
            super().command_position(position, speed, command_id)

    backend = ReentrantBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert len(reentry_errors) == 2
    assert all(
        isinstance(error, GripperGatewayError)
        and 'reentrant gateway' in str(error)
        for error in reentry_errors)
    assert backend.stop_calls == 0
    assert backend.close_count == 0
    assert len(backend.commands) == 1
    assert core.state == GripperGatewayState.EXECUTING


def test_backend_method_lookup_cannot_reenter_close():
    lookup_errors = []
    core = None

    class DescriptorBackend(FakeBackend):
        def __getattribute__(self, name):
            if name == 'command_position' and core is not None:
                try:
                    core.close()
                except Exception as error:
                    lookup_errors.append(error)
                else:
                    raise AssertionError(
                        'method lookup reentry must be rejected')
            return super().__getattribute__(name)

    backend = DescriptorBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert len(lookup_errors) == 1
    assert isinstance(lookup_errors[0], GripperGatewayError)
    assert 'reentrant gateway close is prohibited' in str(lookup_errors[0])
    assert backend.close_count == 0
    assert len(backend.commands) == 1
    assert core.state == GripperGatewayState.EXECUTING


def test_command_id_factory_rejects_objects_without_string_coercion():
    coercion_calls = []
    backend = FakeBackend()

    class ReentrantCommandId:
        def __str__(self):
            coercion_calls.append(True)
            core.close()
            return 'COERCED_COMMAND'

    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
        command_id_factory=lambda: ReentrantCommandId(),
    )
    core.refresh()
    with pytest.raises(GripperGatewayError, match='must return a string'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert coercion_calls == []
    assert backend.close_count == 0
    assert backend.commands == []
    assert core.state == GripperGatewayState.READY
    assert 'AUTH' not in core._used_authorization_ids


def test_command_id_factory_rejects_string_subclass_before_strip():
    strip_calls = []
    backend = FakeBackend()

    class ReentrantString(str):
        def strip(self, *args, **kwargs):
            strip_calls.append(True)
            core.close()
            return super().strip(*args, **kwargs)

    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
        command_id_factory=lambda: ReentrantString('COMMAND'),
    )
    core.refresh()
    with pytest.raises(GripperGatewayError, match='must return a string'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert strip_calls == []
    assert backend.close_count == 0
    assert backend.commands == []
    assert core.state == GripperGatewayState.READY
    assert 'AUTH' not in core._used_authorization_ids


def test_session_revision_and_authorization_reject_subclass_before_strip():
    strip_calls = []
    core, backend, unused_clock = make_core()
    core.refresh()

    class ReentrantString(str):
        def strip(value, *args, **kwargs):
            strip_calls.append(str.__str__(value))
            core.close()
            return str.strip(value, *args, **kwargs)

    with pytest.raises(GripperMotionRejected, match='session id'):
        core.command_position(
            0.2, 0.2, 'AUTH', ReentrantString(core.session_id),
            TOOL_REVISION)
    with pytest.raises(GripperMotionRejected, match='tool revision'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id,
            ReentrantString(TOOL_REVISION))
    with pytest.raises(GripperMotionRejected, match='authorization_id'):
        core.command_position(
            0.2, 0.2, ReentrantString('AUTH'), core.session_id,
            TOOL_REVISION)
    assert strip_calls == []
    assert backend.commands == []
    assert backend.close_count == 0


def test_policy_stop_and_feedback_reject_active_container_subclasses():
    calls = []

    class ActiveString(str):
        def strip(value, *args, **kwargs):
            calls.append('strip')
            return str.strip(value, *args, **kwargs)

    class ActiveDict(dict):
        def get(value, *args, **kwargs):
            calls.append('get')
            return dict.get(value, *args, **kwargs)

    with pytest.raises(ValueError, match='reviewed identity'):
        make_policy(reviewed_tool_model=ActiveString(REVIEWED_TOOL_MODEL)).validate()

    core, backend, unused_clock = make_core()
    core.refresh()
    assert core.request_stop(ActiveString('operator STOP'), core.session_id)
    assert core.state == GripperGatewayState.STOPPING
    assert core.fault_reason == 'stop requested'
    sample = ActiveDict(backend.read_state())
    with pytest.raises(ValueError, match='exact dictionary'):
        core._validated_snapshot(sample, 0.0)

    backend.tool_model = ActiveString(REVIEWED_TOOL_MODEL)
    with pytest.raises(GripperGatewayError, match='identity validation failed'):
        core.refresh()
    assert calls == []
    assert backend.stop_calls == 1


def test_concurrent_same_authorization_sends_exactly_one_command():
    core, backend, unused_clock = make_core()
    core.refresh()
    command_entered = threading.Event()
    release_command = threading.Event()
    loser_done = threading.Event()
    original_command_position = backend.command_position

    def blocking_command_position(position, speed, command_id):
        original_command_position(position, speed, command_id)
        command_entered.set()
        assert release_command.wait(timeout=2.0)

    backend.command_position = blocking_command_position
    start = threading.Barrier(3)
    attempted = []
    both_attempted = threading.Event()
    first_entered = threading.Event()
    release_first = threading.Event()
    original_capture = core._capture_motion_ready_state
    entry_count = []
    validation_barrier = threading.Barrier(2)

    def observed_capture(*args):
        entry_count.append(threading.get_ident())
        if len(entry_count) == 1:
            first_entered.set()
            assert release_first.wait(timeout=2.0)
        return original_capture(*args)

    core._capture_motion_ready_state = observed_capture

    def synchronized_authorization(value, purpose, unused_session_id):
        validation_barrier.wait(timeout=2.0)
        return value == 'AUTH' and purpose == 'motion'

    core._authorization_validator = synchronized_authorization
    outcomes = []

    def worker():
        start.wait(timeout=2.0)
        attempted.append(threading.get_ident())
        if len(attempted) == 2:
            both_attempted.set()
        try:
            command = core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
        except Exception as error:
            outcomes.append(('error', type(error).__name__, str(error)))
            loser_done.set()
        else:
            outcomes.append(('command', command.command_id))

    threads = [threading.Thread(target=worker) for unused in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2.0)
    assert first_entered.wait(timeout=2.0)
    assert both_attempted.wait(timeout=2.0)
    assert len(entry_count) == 1
    release_first.set()
    try:
        assert command_entered.wait(timeout=2.0)
        assert loser_done.wait(timeout=2.0)
    finally:
        release_command.set()
        for thread in threads:
            thread.join(timeout=2.0)
    for thread in threads:
        assert thread.is_alive() is False

    assert len(backend.commands) == 1
    assert len([result for result in outcomes if result[0] == 'command']) == 1
    assert len([result for result in outcomes if result[0] == 'error']) == 1
    assert len(entry_count) == 4
    assert set(entry_count) == set(attempted)
    assert 'AUTH' in core._used_authorization_ids


def test_hung_read_state_does_not_block_stop_and_late_read_is_discarded():
    read_entered = threading.Event()
    release_read = threading.Event()

    class BlockingReadBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.block_reads = False

        def read_state(self):
            sample = super().read_state()
            if self.block_reads:
                read_entered.set()
                assert release_read.wait(timeout=2.0)
            return sample

    backend = BlockingReadBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    backend.block_reads = True
    refresh_outcome = []

    def refresh_worker():
        try:
            refresh_outcome.append(core.refresh())
        except Exception as error:
            refresh_outcome.append(error)

    refresh_thread = threading.Thread(target=refresh_worker)
    refresh_thread.start()
    assert read_entered.wait(timeout=2.0)
    assert core.request_stop('operator stop', core.session_id) is True
    assert backend.stop_calls == 1
    assert core.state == GripperGatewayState.STOPPING
    release_read.set()
    refresh_thread.join(timeout=2.0)
    assert refresh_thread.is_alive() is False
    assert len(refresh_outcome) == 1
    assert isinstance(refresh_outcome[0], GripperGatewayError)
    assert 'superseded' in str(refresh_outcome[0])
    assert core.state == GripperGatewayState.STOPPING
    assert core.snapshot.sequence == 1


def test_hung_read_state_does_not_block_close_and_late_read_stays_closed():
    read_entered = threading.Event()
    release_read = threading.Event()

    class BlockingReadBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.block_reads = False

        def read_state(self):
            sample = super().read_state()
            if self.block_reads:
                read_entered.set()
                assert release_read.wait(timeout=2.0)
            return sample

    backend = BlockingReadBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    backend.block_reads = True
    refresh_outcome = []

    def refresh_worker():
        try:
            refresh_outcome.append(core.refresh())
        except Exception as error:
            refresh_outcome.append(error)

    refresh_thread = threading.Thread(target=refresh_worker)
    refresh_thread.start()
    assert read_entered.wait(timeout=2.0)
    core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert backend.close_count == 1
    release_read.set()
    refresh_thread.join(timeout=2.0)
    assert refresh_thread.is_alive() is False
    assert len(refresh_outcome) == 1
    assert isinstance(refresh_outcome[0], GripperGatewayError)
    assert 'superseded' in str(refresh_outcome[0])
    assert core.state == GripperGatewayState.CLOSED
    assert core.snapshot.sequence == 1


def test_late_refresh_cannot_overwrite_newer_refresh_same_state_epoch():
    read_captured = threading.Event()
    release_read = threading.Event()

    class OneBlockingReadBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.block_next_read = False

        def read_state(self):
            sample = super().read_state()
            if self.block_next_read:
                self.block_next_read = False
                read_captured.set()
                assert release_read.wait(timeout=2.0)
            return sample

    backend = OneBlockingReadBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    state_epoch = core._state_epoch
    backend.position = 0.4
    backend.block_next_read = True
    older_outcome = []

    def older_refresh_worker():
        try:
            older_outcome.append(core.refresh())
        except Exception as error:
            older_outcome.append(error)

    older_refresh = threading.Thread(target=older_refresh_worker)
    older_refresh.start()
    assert read_captured.wait(timeout=2.0)
    backend.position = 0.6
    newer_snapshot = core.refresh()
    committed_generation = core._refresh_generation
    assert core._state_epoch == state_epoch
    assert core.snapshot is newer_snapshot
    assert newer_snapshot.position == 0.6

    release_read.set()
    older_refresh.join(timeout=2.0)
    assert older_refresh.is_alive() is False
    assert len(older_outcome) == 1
    assert isinstance(older_outcome[0], GripperGatewayError)
    assert 'newer refresh generation' in str(older_outcome[0])
    assert core._state_epoch == state_epoch
    assert core._refresh_generation == committed_generation
    assert core.snapshot is newer_snapshot


def test_hung_motion_validator_does_not_block_stop_and_late_validation_loses():
    validator_entered = threading.Event()
    release_validator = threading.Event()

    def validator(unused_value, unused_purpose, unused_session_id):
        validator_entered.set()
        assert release_validator.wait(timeout=2.0)
        return True

    backend = FakeBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=validator,
    )
    core.refresh()
    motion_outcome = []

    def motion_worker():
        try:
            motion_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION))
        except Exception as error:
            motion_outcome.append(error)

    motion_thread = threading.Thread(target=motion_worker)
    motion_thread.start()
    assert validator_entered.wait(timeout=2.0)
    assert core.request_stop('operator stop', core.session_id) is True
    assert backend.stop_calls == 1
    release_validator.set()
    motion_thread.join(timeout=2.0)
    assert motion_thread.is_alive() is False
    assert backend.commands == []
    assert len(motion_outcome) == 1
    assert isinstance(motion_outcome[0], GripperGatewayError)
    assert core.state == GripperGatewayState.STOPPING


def test_hung_motion_validator_does_not_block_close_and_late_validation_loses():
    validator_entered = threading.Event()
    release_validator = threading.Event()

    def validator(unused_value, unused_purpose, unused_session_id):
        validator_entered.set()
        assert release_validator.wait(timeout=2.0)
        return True

    backend = FakeBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=validator,
    )
    core.refresh()
    motion_outcome = []

    def motion_worker():
        try:
            motion_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION))
        except Exception as error:
            motion_outcome.append(error)

    motion_thread = threading.Thread(target=motion_worker)
    motion_thread.start()
    assert validator_entered.wait(timeout=2.0)
    core.close()
    assert core.state == GripperGatewayState.CLOSED
    release_validator.set()
    motion_thread.join(timeout=2.0)
    assert motion_thread.is_alive() is False
    assert backend.commands == []
    assert len(motion_outcome) == 1
    assert isinstance(motion_outcome[0], GripperGatewayError)
    assert core.state == GripperGatewayState.CLOSED


@pytest.mark.parametrize('interrupt', ['stop', 'close'])
def test_hung_ack_validator_does_not_block_safety_interrupt_and_late_ack_loses(
        interrupt):
    validator_entered = threading.Event()
    release_validator = threading.Event()
    block_ack = threading.Event()

    def validator(unused_value, purpose, unused_session_id):
        if purpose == 'ack' and block_ack.is_set():
            validator_entered.set()
            assert release_validator.wait(timeout=2.0)
        return True

    backend = FakeBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=validator,
    )
    backend.valid = False
    core.refresh()
    backend.valid = True
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    block_ack.set()
    ack_outcome = []

    def ack_worker():
        try:
            ack_outcome.append(core.acknowledge_local_fault(
                'ACK', core.session_id))
        except Exception as error:
            ack_outcome.append(error)

    ack_thread = threading.Thread(target=ack_worker)
    ack_thread.start()
    assert validator_entered.wait(timeout=2.0)
    if interrupt == 'stop':
        assert core.request_stop('operator stop', core.session_id) is True
        assert core.state == GripperGatewayState.STOPPING
        assert backend.stop_calls == 1
    else:
        core.close()
        assert core.state == GripperGatewayState.CLOSED
    release_validator.set()
    ack_thread.join(timeout=2.0)
    assert ack_thread.is_alive() is False
    assert len(ack_outcome) == 1
    assert isinstance(ack_outcome[0], GripperGatewayError)
    assert core.state == (
        GripperGatewayState.STOPPING
        if interrupt == 'stop' else GripperGatewayState.CLOSED)


@pytest.mark.parametrize('missing_method', [True, False])
def test_unproven_backend_capabilities_fail_before_any_stop(missing_method):
    class UnprovenBackend(FakeBackend):
        if missing_method:
            SAFETY_CAPABILITIES = None
        else:
            SAFETY_CAPABILITIES = dict(
                FakeBackend.SAFETY_CAPABILITIES,
                bounded_calls_enforced=False,
                native_deadline_enforced=False,
                independent_stop_channel=False,
                native_cancel_enforced=False,
            )

    backend = UnprovenBackend()
    with pytest.raises(ValueError, match='CAPABILITIES|DISABLED/BLOCKED'):
        GripperGatewayCore(
            backend,
            make_policy(),
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.stop_calls == 0
    assert backend.close_count == 0


def test_real_transport_is_blocked_without_release_and_profile_binding():
    class RealBackend(FakeBackend):
        SAFETY_CAPABILITIES = dict(
            FakeBackend.SAFETY_CAPABILITIES,
            execution_mode='REAL',
        )

    backend = RealBackend()
    with pytest.raises(ValueError, match='runtime_release_id'):
        GripperGatewayCore(
            backend,
            make_policy(backend_execution_mode='REAL'),
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.stop_calls == 0
    assert backend.commands == []


def test_real_policy_requires_profile_runtime_and_execution_evidence_hashes():
    values = {
        'backend_execution_mode': 'REAL',
        'runtime_release_id': 'GRIPPER_RUNTIME_R1',
        'release_manifest_sha256': 'a' * 64,
        'motion_profile_id': 'GRIPPER_PROFILE_P1',
        'motion_profile_manifest_sha256': 'b' * 64,
        'motion_profile_runtime_release_id': 'GRIPPER_RUNTIME_R1',
        'approved_speed_grades': (10, 20),
        'persistent_latch_binding': 'c' * 64,
        'backend_method_contract_sha256': 'd' * 64,
        'stop_isolation_architecture_sha256': 'e' * 64,
        'hung_command_stop_test_report_sha256': 'f' * 64,
    }
    cases = (
        ('motion_profile_runtime_release_id', 'STALE_RUNTIME',
         'runtime release ID'),
        ('backend_method_contract_sha256', '',
         'backend_method_contract_sha256'),
        ('stop_isolation_architecture_sha256', 'E' * 64,
         'stop_isolation_architecture_sha256'),
        ('hung_command_stop_test_report_sha256', 'd' * 64,
         'artifacts must be distinct'),
    )
    for field, replacement, match in cases:
        candidate = dict(values)
        candidate[field] = replacement
        with pytest.raises(ValueError, match=match):
            make_policy(**candidate).validate()


def test_capability_method_is_never_called_and_cannot_downgrade_transport():
    class SideEffectBackend(FakeBackend):
        capability_calls = 0

        @staticmethod
        def safety_capabilities():
            SideEffectBackend.capability_calls += 1
            return {'real_transport': False}

    backend = SideEffectBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    assert core.state == GripperGatewayState.INITIALIZING
    assert SideEffectBackend.capability_calls == 0
    assert backend.commands == []
    assert backend.stop_calls == 0
    assert backend.close_count == 0


def test_backend_legacy_real_transport_flag_is_rejected_before_operations():
    class LegacyCapabilityBackend(FakeBackend):
        SAFETY_CAPABILITIES = dict(
            FakeBackend.SAFETY_CAPABILITIES,
            real_transport=False,
        )

    backend = LegacyCapabilityBackend()
    with pytest.raises(ValueError, match='keys do not match'):
        GripperGatewayCore(
            backend,
            make_policy(),
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.commands == []
    assert backend.stop_calls == 0
    assert backend.close_count == 0


def test_backend_execution_mode_rejects_string_subclass_before_operations():
    class ModeString(str):
        pass

    class InexactModeBackend(FakeBackend):
        SAFETY_CAPABILITIES = dict(
            FakeBackend.SAFETY_CAPABILITIES,
            execution_mode=ModeString('PURE_FAKE'),
        )

    backend = InexactModeBackend()
    with pytest.raises(ValueError, match='exact string'):
        GripperGatewayCore(
            backend,
            make_policy(),
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.commands == []
    assert backend.stop_calls == 0
    assert backend.close_count == 0


def test_real_backend_binding_must_match_policy_exactly_before_operations():
    release_sha = 'a' * 64
    profile_sha = 'b' * 64
    method_sha = 'd' * 64
    isolation_sha = 'e' * 64
    hung_stop_sha = 'f' * 64
    policy = make_policy(
        backend_execution_mode='REAL',
        runtime_release_id='GRIPPER_RUNTIME_R1',
        release_manifest_sha256=release_sha,
        motion_profile_id='GRIPPER_PROFILE_P1',
        motion_profile_manifest_sha256=profile_sha,
        motion_profile_runtime_release_id='GRIPPER_RUNTIME_R1',
        approved_speed_grades=(10, 20),
        backend_method_contract_sha256=method_sha,
        stop_isolation_architecture_sha256=isolation_sha,
        hung_command_stop_test_report_sha256=hung_stop_sha,
        persistent_latch_binding='c' * 64,
    )

    class StaleRealBackend(FakeBackend):
        SAFETY_CAPABILITIES = dict(
            FakeBackend.SAFETY_CAPABILITIES,
            execution_mode='REAL',
            release_binding={
                'runtime_release_id': 'GRIPPER_RUNTIME_R1',
                'release_manifest_sha256': release_sha,
                'motion_profile_id': 'GRIPPER_PROFILE_P1',
                'motion_profile_manifest_sha256': profile_sha,
                'motion_profile_runtime_release_id': 'GRIPPER_RUNTIME_R1',
                'approved_speed_grades': (10,),
                'backend_method_contract_sha256': method_sha,
                'stop_isolation_architecture_sha256': isolation_sha,
                'hung_command_stop_test_report_sha256': hung_stop_sha,
            },
            persistent_latch_binding='c' * 64,
        )

    backend = StaleRealBackend()
    with pytest.raises(ValueError, match='manifest SHA.*speed grade binding'):
        GripperGatewayCore(
            backend,
            policy,
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.commands == []
    assert backend.stop_calls == 0
    assert backend.close_count == 0


def test_exact_real_metadata_still_cannot_self_authorize_construction():
    release_sha = 'a' * 64
    profile_sha = 'b' * 64
    latch_sha = 'c' * 64
    method_sha = 'd' * 64
    isolation_sha = 'e' * 64
    hung_stop_sha = 'f' * 64
    policy = make_policy(
        backend_execution_mode='REAL',
        runtime_release_id='GRIPPER_RUNTIME_R1',
        release_manifest_sha256=release_sha,
        motion_profile_id='GRIPPER_PROFILE_P1',
        motion_profile_manifest_sha256=profile_sha,
        motion_profile_runtime_release_id='GRIPPER_RUNTIME_R1',
        approved_speed_grades=(10, 20),
        backend_method_contract_sha256=method_sha,
        stop_isolation_architecture_sha256=isolation_sha,
        hung_command_stop_test_report_sha256=hung_stop_sha,
        persistent_latch_binding=latch_sha,
    )

    class SelfAttestedRealBackend(FakeBackend):
        SAFETY_CAPABILITIES = dict(
            FakeBackend.SAFETY_CAPABILITIES,
            execution_mode='REAL',
            release_binding={
                'runtime_release_id': 'GRIPPER_RUNTIME_R1',
                'release_manifest_sha256': release_sha,
                'motion_profile_id': 'GRIPPER_PROFILE_P1',
                'motion_profile_manifest_sha256': profile_sha,
                'motion_profile_runtime_release_id': 'GRIPPER_RUNTIME_R1',
                'approved_speed_grades': (10, 20),
                'backend_method_contract_sha256': method_sha,
                'stop_isolation_architecture_sha256': isolation_sha,
                'hung_command_stop_test_report_sha256': hung_stop_sha,
            },
            persistent_latch_binding=latch_sha,
        )

    backend = SelfAttestedRealBackend()
    with pytest.raises(ValueError, match='cannot independently verify'):
        GripperGatewayCore(
            backend,
            policy,
            clock=FakeClock(),
            authorization_validator=lambda value, purpose, session_id: True,
        )
    assert backend.commands == []
    assert backend.stop_calls == 0
    assert backend.close_count == 0


@pytest.mark.parametrize('fail_stop', [False, True])
def test_blocked_stop_then_close_preserves_closed_and_defers_transport_close(
        fail_stop):
    stop_entered = threading.Event()
    release_stop = threading.Event()
    overlap = []

    class BlockingStopBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.stop_active = False

        def stop(self):
            self.stop_calls += 1
            self.stop_active = True
            stop_entered.set()
            assert release_stop.wait(timeout=2.0)
            self.stop_active = False
            if fail_stop:
                raise RuntimeError('late stop failure')
            self.moving = False

        def close(self):
            overlap.append(self.stop_active)
            super().close()

    backend = BlockingStopBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    stop_outcome = []

    def stop_worker():
        try:
            stop_outcome.append(core.request_stop(
                'operator stop', core.session_id))
        except Exception as error:
            stop_outcome.append(error)

    stop_thread = threading.Thread(target=stop_worker)
    stop_thread.start()
    assert stop_entered.wait(timeout=2.0)
    with pytest.raises(GripperGatewayError, match='deferred'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert backend.close_count == 0
    assert overlap == []
    release_stop.set()
    stop_thread.join(timeout=2.0)
    assert stop_thread.is_alive() is False
    assert len(stop_outcome) == 1
    assert isinstance(stop_outcome[0], GripperGatewayError)
    assert core.state == GripperGatewayState.CLOSED
    assert backend.close_count == 1
    assert backend.closed is True
    assert overlap == [False]
    if fail_stop:
        assert core.physical_stop_required is True
        assert 'STOP failed after gateway close' in core.fault_reason


def test_action_boundary_does_not_wait_for_blocked_stop_or_emit_second_stop():
    stop_entered = threading.Event()
    release_stop = threading.Event()

    class BlockingStopBackend(FakeBackend):
        def stop(self):
            self.stop_calls += 1
            self.moving = False
            stop_entered.set()
            assert release_stop.wait(timeout=2.0)

    backend = BlockingStopBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    stop_outcome = []

    def stop_worker():
        try:
            stop_outcome.append(core.request_stop(
                'blocking stop', core.session_id))
        except Exception as error:
            stop_outcome.append(error)

    stop_thread = threading.Thread(target=stop_worker)
    stop_thread.start()
    assert stop_entered.wait(timeout=2.0)
    boundary_outcome = []
    boundary_thread = threading.Thread(
        target=lambda: boundary_outcome.append(
            core.fail_closed_action_boundary('action deadline ended')))
    boundary_thread.start()
    boundary_thread.join(timeout=0.2)
    boundary_was_blocked = boundary_thread.is_alive()

    release_stop.set()
    stop_thread.join(timeout=2.0)
    boundary_thread.join(timeout=2.0)

    assert boundary_was_blocked is False
    assert stop_thread.is_alive() is False
    assert boundary_thread.is_alive() is False
    assert boundary_outcome == [True]
    assert backend.stop_calls == 1
    assert len(stop_outcome) == 1
    assert isinstance(stop_outcome[0], GripperGatewayError)
    assert 'PHYSICAL EMERGENCY STOP' in str(stop_outcome[0])
    assert core.state not in (
        GripperGatewayState.READY, GripperGatewayState.EXECUTING)
    assert core.physical_stop_required is True


def test_feedback_captured_before_stop_return_cannot_count_stationary():
    stop_entered = threading.Event()
    release_stop = threading.Event()
    feedback_captured = threading.Event()
    release_feedback = threading.Event()

    class BlockingStopAndLateReadBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.block_next_read = False

        def read_state(self):
            sample = super().read_state()
            if self.block_next_read:
                self.block_next_read = False
                feedback_captured.set()
                assert release_feedback.wait(timeout=2.0)
            return sample

        def stop(self):
            self.stop_calls += 1
            self.position = 0.2
            self.moving = False
            stop_entered.set()
            assert release_stop.wait(timeout=2.0)

    backend = BlockingStopAndLateReadBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    pre_stop_epoch = core._state_epoch
    stop_outcome = []
    stop_thread = threading.Thread(
        target=lambda: stop_outcome.append(core.request_stop(
            'operator stop', core.session_id)))
    stop_thread.start()
    assert stop_entered.wait(timeout=2.0)
    reservation_epoch = core._state_epoch
    assert reservation_epoch == pre_stop_epoch + 1

    core.refresh()
    pre_stop_return_snapshot = core.snapshot
    assert core._stable_samples == 0
    assert core._stationary_since is None
    assert core._fault_stationary_verified is False

    backend.block_next_read = True
    late_refresh_outcome = []

    def late_refresh_worker():
        try:
            late_refresh_outcome.append(core.refresh())
        except Exception as error:
            late_refresh_outcome.append(error)

    late_refresh = threading.Thread(target=late_refresh_worker)
    late_refresh.start()
    assert feedback_captured.wait(timeout=2.0)
    late_refresh_generation = core._refresh_generation
    release_stop.set()
    stop_thread.join(timeout=2.0)
    assert stop_thread.is_alive() is False
    assert stop_outcome == [True]
    stop_commit_epoch = core._state_epoch
    assert stop_commit_epoch == reservation_epoch + 1
    assert core._refresh_generation == late_refresh_generation

    release_feedback.set()
    late_refresh.join(timeout=2.0)
    assert late_refresh.is_alive() is False
    assert len(late_refresh_outcome) == 1
    assert isinstance(late_refresh_outcome[0], GripperGatewayError)
    assert 'superseded' in str(late_refresh_outcome[0])
    assert core._state_epoch == stop_commit_epoch
    assert core._refresh_generation == late_refresh_generation
    assert core.snapshot is pre_stop_return_snapshot
    assert core.state == GripperGatewayState.STOPPING
    assert core._stable_samples == 0
    assert core._stationary_since is None
    assert core._fault_stationary_verified is False

    core.refresh()
    assert core.state == GripperGatewayState.STOPPING
    assert core._stable_samples == 1
    clock.advance(0.21)
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._fault_stationary_verified is True


def test_feedback_captured_before_command_activation_cannot_complete_command():
    command_entered = threading.Event()
    release_command = threading.Event()
    feedback_captured = threading.Event()
    release_feedback = threading.Event()

    class BlockingCommandAndLateReadBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.block_next_read = False

        def command_position(self, position, speed, command_id):
            super().command_position(position, speed, command_id)
            self.position = position
            self.moving = False
            command_entered.set()
            assert release_command.wait(timeout=2.0)

        def read_state(self):
            sample = super().read_state()
            if self.block_next_read:
                self.block_next_read = False
                feedback_captured.set()
                assert release_feedback.wait(timeout=2.0)
            return sample

    backend = BlockingCommandAndLateReadBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    command_outcome = []
    pre_activation_epoch = core._state_epoch

    def command_worker():
        try:
            command_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION))
        except Exception as error:
            command_outcome.append(error)

    command_thread = threading.Thread(target=command_worker)
    command_thread.start()
    assert command_entered.wait(timeout=2.0)

    core.refresh()
    pre_activation_snapshot = core.snapshot
    assert core.state == GripperGatewayState.READY
    assert core.last_result is None
    assert core._stable_samples == 0

    backend.block_next_read = True
    late_refresh_outcome = []

    def late_refresh_worker():
        try:
            late_refresh_outcome.append(core.refresh())
        except Exception as error:
            late_refresh_outcome.append(error)

    late_refresh = threading.Thread(target=late_refresh_worker)
    late_refresh.start()
    assert feedback_captured.wait(timeout=2.0)
    late_refresh_generation = core._refresh_generation
    release_command.set()
    command_thread.join(timeout=2.0)
    assert command_thread.is_alive() is False
    assert len(command_outcome) == 1
    assert not isinstance(command_outcome[0], Exception)
    activation_epoch = core._state_epoch
    assert activation_epoch == pre_activation_epoch + 1
    assert core._refresh_generation == late_refresh_generation

    release_feedback.set()
    late_refresh.join(timeout=2.0)
    assert late_refresh.is_alive() is False
    assert len(late_refresh_outcome) == 1
    assert isinstance(late_refresh_outcome[0], GripperGatewayError)
    assert 'superseded' in str(late_refresh_outcome[0])
    assert core._state_epoch == activation_epoch
    assert core._refresh_generation == late_refresh_generation
    assert core.snapshot is pre_activation_snapshot
    assert core.state == GripperGatewayState.EXECUTING
    assert core.last_result is None
    assert core._stable_samples == 0

    core.refresh()
    assert core.state == GripperGatewayState.EXECUTING
    assert core._stable_samples == 1
    clock.advance(0.21)
    core.refresh()
    assert core.state == GripperGatewayState.READY
    assert core.last_result.success is True


def test_stop_reservation_blocks_motion_before_stop_clock_returns():
    stop_clock_entered = threading.Event()
    release_stop_clock = threading.Event()
    clock_calls = []

    def clock():
        clock_calls.append(True)
        if len(clock_calls) == 2:
            stop_clock_entered.set()
            assert release_stop_clock.wait(timeout=2.0)
        return 0.0

    backend = FakeBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    stop_outcome = []

    def stop_worker():
        try:
            stop_outcome.append(core.request_stop(
                'operator stop', core.session_id))
        except Exception as error:
            stop_outcome.append(error)

    stop_thread = threading.Thread(target=stop_worker)
    stop_thread.start()
    assert stop_clock_entered.wait(timeout=2.0)
    assert core.motion_safety_unresolved is True
    assert core.state == GripperGatewayState.STOPPING
    with pytest.raises(GripperMotionRejected, match='STOP'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    release_stop_clock.set()
    stop_thread.join(timeout=2.0)
    assert stop_thread.is_alive() is False
    assert stop_outcome == [True]
    assert backend.commands == []


def test_close_between_stop_clock_and_commit_clears_stop_reservation():
    backend = FakeBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    original_read_clock = core._read_clock
    close_outcome = []

    def close_after_epoch_check(context, expected_epoch=None):
        value = original_read_clock(context, expected_epoch=expected_epoch)
        try:
            core.close()
        except Exception as error:
            close_outcome.append(error)
        else:
            close_outcome.append(None)
        return value

    core._read_clock = close_after_epoch_check
    with pytest.raises(GripperGatewayError, match='superseded'):
        core.request_stop('operator stop', core.session_id)

    assert len(close_outcome) == 1
    assert isinstance(close_outcome[0], GripperGatewayError)
    assert 'PHYSICAL' in str(close_outcome[0])
    assert core.state == GripperGatewayState.CLOSED
    assert core._stop_send_in_progress is False
    assert backend.stop_calls == 0
    assert backend.close_count == 1


def test_emergency_stop_gate_skips_transport_if_close_wins_race():
    stop_gate_entered = threading.Event()
    release_stop_gate = threading.Event()

    class ObservableBackend(FakeBackend):
        def stop(self):
            raise AssertionError('STOP must not be called after backend close')

    backend = ObservableBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    with core._lock:
        core._motion_send_in_progress = True
    original_emergency = core._send_uncredited_emergency_stop

    def paused_emergency():
        stop_gate_entered.set()
        assert release_stop_gate.wait(timeout=2.0)
        return original_emergency()

    core._send_uncredited_emergency_stop = paused_emergency
    boundary_outcome = []

    def boundary_worker():
        try:
            boundary_outcome.append(core.fail_closed_action_boundary(
                'action boundary ended'))
        except Exception as error:
            boundary_outcome.append(error)

    boundary_thread = threading.Thread(target=boundary_worker)
    boundary_thread.start()
    assert stop_gate_entered.wait(timeout=2.0)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert backend.close_count == 1
    release_stop_gate.set()
    boundary_thread.join(timeout=2.0)
    assert boundary_thread.is_alive() is False
    assert boundary_outcome == [True]
    assert backend.stop_calls == 0
    assert core.state == GripperGatewayState.CLOSED


def test_all_backend_stop_emitters_are_serialized_helpers():
    ast = __import__('ast')
    inspect = __import__('inspect')
    source = inspect.getsource(GripperGatewayCore)
    tree = ast.parse(source)
    emitters = []
    for function in (
            item for item in tree.body[0].body
            if isinstance(item, ast.FunctionDef)):
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == '_call_external_method'
                    and len(call.args) >= 3
                    and isinstance(call.args[2], ast.Constant)
                    and call.args[2].value == 'stop'):
                emitters.append(function.name)
    assert sorted(emitters) == [
        '_send_stop_attempt', '_send_uncredited_emergency_stop']
    regular_source = inspect.getsource(
        GripperGatewayCore._send_stop_attempt)
    emergency_source = inspect.getsource(
        GripperGatewayCore._send_uncredited_emergency_stop)
    assert 'with self._stop_lock:' in regular_source
    assert 'self._stop_lock.acquire(blocking=False)' in emergency_source
    assert 'self._stop_lock.release()' in emergency_source
    assert 'with self._stop_lock:' not in emergency_source


def test_stop_does_not_wait_for_hung_send_and_late_send_cannot_commit():
    command_entered = threading.Event()
    release_command = threading.Event()
    stop_attempted = threading.Event()

    class BlockingBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            command_entered.set()
            assert release_command.wait(timeout=2.0)
            super().command_position(position, speed, command_id)

    backend = BlockingBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    command_outcome = []
    stop_outcome = []

    def command_worker():
        try:
            command_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION))
        except Exception as error:
            command_outcome.append(error)

    def stop_worker():
        stop_attempted.set()
        try:
            stop_outcome.append(
                core.request_stop('concurrent stop', core.session_id))
        except Exception as error:
            stop_outcome.append(error)

    command_thread = threading.Thread(target=command_worker)
    command_thread.start()
    assert command_entered.wait(timeout=2.0)
    stop_thread = threading.Thread(target=stop_worker)
    stop_thread.start()
    assert stop_attempted.wait(timeout=2.0)
    stop_thread.join(timeout=0.5)
    assert stop_thread.is_alive() is False
    assert stop_outcome == [True]
    assert backend.stop_calls == 1
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    release_command.set()
    command_thread.join(timeout=2.0)
    assert command_thread.is_alive() is False

    assert len(backend.commands) == 1
    assert backend.stop_calls == 1
    assert len(command_outcome) == 1
    assert len(stop_outcome) == 1
    assert isinstance(command_outcome[0], GripperGatewayError)
    assert 'activation is refused' in str(command_outcome[0])
    assert core.physical_stop_required is True
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.active_command is None


def test_core_does_not_claim_to_bound_an_arbitrary_backend_call():
    source = __import__('inspect').getsource(
        GripperGatewayCore.command_position)
    assert 'the injected backend owns its deadline' in source
    assert 'does not make an arbitrary backend' in source
    assert 'call bounded' in source


def test_close_does_not_wait_for_hung_send_and_late_send_cannot_commit():
    command_entered = threading.Event()
    release_command = threading.Event()
    close_attempted = threading.Event()

    class BlockingBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            command_entered.set()
            assert release_command.wait(timeout=2.0)
            super().command_position(position, speed, command_id)

    backend = BlockingBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    command_outcome = []
    close_outcome = []

    def command_worker():
        try:
            command_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION))
        except Exception as error:
            command_outcome.append(error)

    def close_worker():
        close_attempted.set()
        try:
            core.close()
        except Exception as error:
            close_outcome.append(error)
        else:
            close_outcome.append(None)

    command_thread = threading.Thread(target=command_worker)
    command_thread.start()
    assert command_entered.wait(timeout=2.0)
    close_thread = threading.Thread(target=close_worker)
    close_thread.start()
    assert close_attempted.wait(timeout=2.0)
    close_thread.join(timeout=0.5)
    assert close_thread.is_alive() is False
    assert backend.stop_calls == 1
    assert backend.close_count == 1
    assert core.state == GripperGatewayState.CLOSED
    release_command.set()
    command_thread.join(timeout=2.0)
    assert command_thread.is_alive() is False

    assert len(backend.commands) == 1
    assert backend.stop_calls == 1
    assert backend.close_count == 1
    assert core.state == GripperGatewayState.CLOSED
    assert core.active_command is None
    assert core.physical_stop_required is True
    assert len(close_outcome) == 1
    assert isinstance(close_outcome[0], GripperGatewayError)
    assert isinstance(command_outcome[0], GripperGatewayError)
    assert 'gateway is closed' in str(command_outcome[0])
    with pytest.raises(GripperGatewayError, match='closed'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id,
            TOOL_REVISION)
    assert core.state == GripperGatewayState.CLOSED


@pytest.mark.parametrize('field,unsafe_value', [
    ('connected', False),
    ('valid', False),
    ('enabled', False),
    ('fault_code', 7),
])
def test_unhealthy_moving_feedback_stops_once_and_stays_physical(
        field, unsafe_value):
    core, backend, unused_clock = make_core()
    core.refresh()
    backend.moving = True
    setattr(backend, field, unsafe_value)

    snapshot = core.refresh()

    assert snapshot.moving is True
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    assert core._fault_stationary_verified is False
    assert backend.stop_calls == 1

    core.refresh()
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()

    assert core.state == GripperGatewayState.CLOSED
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    assert backend.close_count == 1


def test_unhealthy_moving_stop_failure_is_attempted_once_and_stays_physical():
    core, backend, unused_clock = make_core()
    core.refresh()
    backend.moving = True
    backend.valid = False
    backend.fail_stop = True

    core.refresh()

    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    core.refresh()
    assert backend.stop_calls == 1
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    assert backend.stop_calls == 1


def test_unhealthy_moving_blocked_stop_deadline_escalates_without_second_stop():
    stop_entered = threading.Event()
    release_stop = threading.Event()

    class BlockingUnhealthyStopBackend(FakeBackend):
        def stop(self):
            self.stop_calls += 1
            stop_entered.set()
            assert release_stop.wait(timeout=2.0)
            self.moving = False

    backend = BlockingUnhealthyStopBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
    )
    core.refresh()
    backend.moving = True
    backend.valid = False
    refresh_outcome = []

    def refresh_worker():
        try:
            refresh_outcome.append(core.refresh())
        except Exception as error:
            refresh_outcome.append(error)

    refresh_thread = threading.Thread(target=refresh_worker)
    refresh_thread.start()
    assert stop_entered.wait(timeout=2.0)
    assert core.state == GripperGatewayState.STOPPING
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is False
    assert backend.stop_calls == 1

    assert core.fail_closed_action_boundary(
        'native STOP deadline expired') is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert backend.close_count == 0

    release_stop.set()
    refresh_thread.join(timeout=2.0)
    assert refresh_thread.is_alive() is False
    assert len(refresh_outcome) == 1
    assert not isinstance(refresh_outcome[0], Exception)
    assert backend.stop_calls == 1
    assert backend.close_count == 1
    assert core.physical_stop_required is True


@pytest.mark.parametrize('drift_field,drift_value', [
    ('tool_model', 'UNREVIEWED_MODEL'),
    ('controller_boot_id', 'BOOT_B'),
])
def test_identity_or_boot_drift_while_moving_stops_once_and_locks_process(
        drift_field, drift_value):
    core, backend, unused_clock = make_core()
    core.refresh()
    backend.moving = True
    setattr(backend, drift_field, drift_value)

    snapshot = core.refresh()

    assert snapshot.moving is True
    assert core._identity_lockout is True
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    core.refresh()
    assert backend.stop_calls == 1
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)


@pytest.mark.parametrize('stale_field', ['sequence', 'sample_timestamp'])
def test_stale_moving_feedback_stops_once_and_cannot_restore_ready(stale_field):
    core, backend, unused_clock = make_core()
    accepted = core.refresh()
    backend.moving = True
    if stale_field == 'sequence':
        backend.sequence = accepted.sequence
        backend.auto_increment_sequence = False
    else:
        backend.sample_timestamp = accepted.sample_timestamp
        backend.auto_increment_timestamp = False

    rejected = core.refresh()

    assert rejected.moving is True
    assert core.snapshot is accepted
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    core.refresh()
    assert backend.stop_calls == 1
    assert core.state != GripperGatewayState.READY
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK-STALE', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    assert backend.close_count == 1


def test_unhealthy_feedback_during_blocked_send_uses_one_independent_stop():
    command_entered = threading.Event()
    release_command = threading.Event()

    class BlockingLateAcceptBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            command_entered.set()
            assert release_command.wait(timeout=2.0)
            super().command_position(position, speed, command_id)

    backend = BlockingLateAcceptBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
        command_id_factory=lambda: 'BLOCKED-UNHEALTHY-COMMAND',
    )
    core.refresh()
    command_outcome = []

    def command_worker():
        try:
            command_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH-BLOCKED-UNHEALTHY', core.session_id,
                TOOL_REVISION))
        except Exception as error:
            command_outcome.append(error)

    command_thread = threading.Thread(target=command_worker)
    command_thread.start()
    assert command_entered.wait(timeout=2.0)
    backend.moving = True
    backend.valid = False

    snapshot = core.refresh()

    assert snapshot.moving is True
    assert core._motion_send_in_progress is True
    assert core._fault_stationary_verified is False
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK-BLOCKED', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert backend.stop_calls == 1

    release_command.set()
    command_thread.join(timeout=2.0)
    assert command_thread.is_alive() is False
    assert len(command_outcome) == 1
    assert isinstance(command_outcome[0], GripperGatewayError)
    assert backend.moving is True
    assert backend.stop_calls == 1
    assert core.state == GripperGatewayState.CLOSED
    assert core.physical_stop_required is True


def test_pending_pre_stop_send_cannot_gain_stationary_or_ack_credit():
    command_entered = threading.Event()
    release_command = threading.Event()

    class BlockingLateAcceptBackend(FakeBackend):
        def command_position(self, position, speed, command_id):
            command_entered.set()
            assert release_command.wait(timeout=2.0)
            super().command_position(position, speed, command_id)

    backend = BlockingLateAcceptBackend()
    clock = FakeClock()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=clock,
        authorization_validator=lambda value, purpose, session_id: True,
        command_id_factory=lambda: 'PENDING-PRE-STOP-COMMAND',
    )
    core.refresh()
    command_outcome = []

    def command_worker():
        try:
            command_outcome.append(core.command_position(
                0.2, 0.2, 'AUTH-PENDING-PRE-STOP', core.session_id,
                TOOL_REVISION))
        except Exception as error:
            command_outcome.append(error)

    command_thread = threading.Thread(target=command_worker)
    command_thread.start()
    assert command_entered.wait(timeout=2.0)
    assert core.request_stop('stop pending send', core.session_id) is True
    assert backend.stop_calls == 1
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True

    core.refresh()
    clock.advance(0.21)
    core.refresh()
    clock.advance(0.21)
    core.refresh()

    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._motion_send_in_progress is True
    assert core._fault_stationary_verified is False
    assert core._stable_samples == 0
    assert core.motion_safety_unresolved is True
    assert core.physical_stop_required is True
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK-PENDING', core.session_id)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('duplicate stop', core.session_id)
    assert backend.stop_calls == 1
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1

    release_command.set()
    command_thread.join(timeout=2.0)
    assert command_thread.is_alive() is False
    assert len(command_outcome) == 1
    assert isinstance(command_outcome[0], GripperGatewayError)
    assert backend.moving is True
    assert backend.stop_calls == 1
    assert core.physical_stop_required is True


def test_static_motion_gate_rejects_even_with_healthy_state():
    core, unused_backend, unused_clock = make_core(permit_motion=False)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='static policy'):
        core.command_position(
            0.4, 0.2, 'AUTH', core.session_id, TOOL_REVISION)


def test_session_authorization_and_command_id_contract():
    core, backend, unused_clock = make_core()
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='session'):
        core.command_position(0.4, 0.2, 'AUTH', 'stale', TOOL_REVISION)
    with pytest.raises(GripperMotionRejected, match='authorization'):
        core.command_position(0.4, 0.2, '', core.session_id, TOOL_REVISION)
    command = core.command_position(
        0.4, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert command.command_id
    assert backend.commands == [(0.4, 0.2, command.command_id)]
    assert core.state == GripperGatewayState.EXECUTING


def test_success_requires_fresh_feedback_not_setter_return():
    core, backend, unused_clock = make_core()
    core.refresh()
    command = core.command_position(
        0.4, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert core.last_result is None
    backend.moving = False
    backend.position = 0.4
    core.refresh()
    assert core.state == GripperGatewayState.EXECUTING
    assert core.last_result is None
    clock = core._clock
    clock.advance(0.2)
    core.refresh()
    assert core.state == GripperGatewayState.READY
    assert core.last_result.command_id == command.command_id
    assert core.last_result.success is True


def test_feedback_command_id_mismatch_or_rollback_fails_closed():
    core, backend, unused_clock = make_core()
    core.refresh()
    command = core.command_position(
        0.4, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.moving = False
    backend.position = 0.4
    backend.reported_command_id = 'older-command-id'
    core.refresh()
    assert core.state == GripperGatewayState.STOPPING
    assert backend.stop_calls == 1
    assert core.active_command.command_id == command.command_id
    assert core.last_result is None

    duplicate_ids = iter(('fixed-command', 'fixed-command'))
    duplicate_core, duplicate_backend, duplicate_clock = make_core(
        command_id_factory=lambda: next(duplicate_ids))
    duplicate_core.refresh()
    first = duplicate_core.command_position(
        0.4, 0.2, 'AUTH', duplicate_core.session_id, TOOL_REVISION)
    duplicate_backend.moving = False
    duplicate_backend.position = 0.4
    duplicate_backend.reported_command_id = first.command_id
    duplicate_core.refresh()
    duplicate_clock.advance(0.2)
    duplicate_core.refresh()
    with pytest.raises(GripperGatewayError, match='already been issued'):
        duplicate_core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', duplicate_core.session_id,
            TOOL_REVISION)
    assert len(duplicate_backend.commands) == 1
    assert duplicate_core.state == GripperGatewayState.FAULT_LATCHED


def test_stop_requires_distinct_fresh_stationary_samples_and_dwell():
    core, backend, clock = make_core(stable_samples=2)
    core.refresh()
    command = core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert core.request_stop('operator stop', core.session_id) is True
    assert core.state == GripperGatewayState.STOPPING
    assert backend.stop_calls == 1
    core.refresh()
    assert core.state == GripperGatewayState.STOPPING
    clock.advance(0.2)
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.last_result.command_id == command.command_id
    assert core.last_result.success is False


def test_ack_requires_authorization_and_stationary_evidence():
    core, unused_backend, clock = make_core(stable_samples=2)
    core.refresh()
    core.request_stop('test stop', core.session_id)
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='authorization'):
        core.acknowledge_local_fault('', core.session_id)
    assert core.acknowledge_local_fault('HUMAN_ACK', core.session_id)
    assert core.state == GripperGatewayState.READY


def test_session_mismatch_and_replayed_authorizations_are_rejected():
    core, backend, clock = make_core(stable_samples=2)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='session'):
        core.request_stop('bad session', 'stale')
    with pytest.raises(GripperMotionRejected, match='does not match motion'):
        core.command_position(
            0.4, 0.2, 'BAD_AUTH', core.session_id, TOOL_REVISION)
    command = core.command_position(
        0.4, 0.2, 'MOVE_AUTH', core.session_id, TOOL_REVISION)
    backend.moving = False
    backend.position = 0.4
    backend.reported_command_id = command.command_id
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='consumed'):
        core.command_position(
            0.3, 0.2, 'MOVE_AUTH', core.session_id, TOOL_REVISION)
    core.request_stop('ack setup', core.session_id)
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    assert core.acknowledge_local_fault('ACK_AUTH', core.session_id)
    core.request_stop('second ack setup', core.session_id)
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='consumed'):
        core.acknowledge_local_fault('ACK_AUTH', core.session_id)
    with pytest.raises(GripperMotionRejected, match='does not match ack'):
        core.acknowledge_local_fault('BAD_ACK', core.session_id)


def test_authorization_validator_is_mandatory_and_purpose_bound():
    clock = FakeClock()
    backend = FakeBackend()
    policy = GripperGatewayPolicy(
        permit_motion=True,
        reviewed_tool_model=REVIEWED_TOOL_MODEL,
        reviewed_tool_revision=REVIEWED_TOOL_REVISION,
        reviewed_controller_identity=REVIEWED_CONTROLLER_IDENTITY,
        reviewed_transport_identity=REVIEWED_TRANSPORT_IDENTITY,
        reviewed_protocol_identity=REVIEWED_PROTOCOL_IDENTITY,
        state_max_age_s=0.5,
        command_timeout_s=1.0,
        stop_timeout_s=0.5,
        stable_samples_required=2,
        position_tolerance=0.02,
        stationary_position_tolerance=0.01,
        stationary_dwell_s=0.2,
    )
    core = GripperGatewayCore(backend, policy, clock=clock)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='not configured'):
        core.command_position(
            0.4, 0.2, 'AUTH', core.session_id, TOOL_REVISION)


def test_policy_requires_multiple_stationary_samples():
    with pytest.raises(ValueError, match='at least 2'):
        GripperGatewayPolicy(
            permit_motion=True,
            reviewed_tool_model=REVIEWED_TOOL_MODEL,
            reviewed_tool_revision=REVIEWED_TOOL_REVISION,
            reviewed_controller_identity=REVIEWED_CONTROLLER_IDENTITY,
            reviewed_transport_identity=REVIEWED_TRANSPORT_IDENTITY,
            reviewed_protocol_identity=REVIEWED_PROTOCOL_IDENTITY,
            state_max_age_s=0.5,
            command_timeout_s=1.0,
            stop_timeout_s=0.5,
            stable_samples_required=1,
            position_tolerance=0.02,
            stationary_position_tolerance=0.01,
            stationary_dwell_s=0.2,
        ).validate()


@pytest.mark.parametrize(
    'overrides,match',
    (
        ({'command_timeout_s': 0.2}, 'command_timeout_s'),
        ({'stop_timeout_s': 0.2}, 'stop_timeout_s'),
    ),
)
def test_policy_timeouts_must_exceed_stationary_dwell(overrides, match):
    with pytest.raises(ValueError, match=match):
        make_policy(**overrides).validate()


def test_snapshot_valid_requires_fresh_healthy_reviewed_state():
    core, backend, clock = make_core()
    assert core.snapshot_is_valid() is False
    core.refresh()
    assert core.snapshot_is_valid() is True
    clock.advance(0.6)
    assert core.snapshot_is_valid() is False

    fresh_core, fresh_backend, unused_clock = make_core()
    fresh_core.refresh()
    fresh_backend.valid = False
    fresh_core.refresh()
    assert fresh_core.snapshot_is_valid() is False


def test_stop_feedback_command_id_mismatch_clears_stationary_evidence():
    core, backend, unused_clock = make_core(stable_samples=2)
    core.refresh()
    command = core.command_position(
        0.3, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    core.request_stop('operator stop', core.session_id)
    backend.reported_command_id = command.command_id
    core.refresh()
    assert core._stable_samples == 1
    backend.reported_command_id = 'rolled-back-command'
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._stable_samples == 0
    assert core._fault_stationary_verified is False


def test_command_timeout_sends_stop_and_never_retries_command():
    core, backend, clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    clock.advance(1.1)
    core.refresh()
    assert core.state == GripperGatewayState.STOPPING
    assert backend.stop_calls == 1
    assert len(backend.commands) == 1


def test_command_send_exception_attempts_one_best_effort_stop():
    core, backend, unused_clock = make_core()
    core.refresh()
    backend.fail_command = True
    with pytest.raises(GripperGatewayError, match='command send failed'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert backend.stop_calls == 1
    assert len(backend.commands) == 1
    assert 'best-effort STOP sent' in core.fault_reason


def test_command_send_exception_consumes_authorization_and_command_id():
    command_ids = iter(('accepted-before-error', 'accepted-before-error'))
    core, backend, clock = make_core(
        stable_samples=2, command_id_factory=lambda: next(command_ids))
    core.refresh()
    backend.fail_command = True
    with pytest.raises(GripperGatewayError, match='command send failed'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert backend.commands == [(0.2, 0.2, 'accepted-before-error')]
    assert 'AUTH' in core._used_authorization_ids
    assert 'accepted-before-error' in core._issued_command_ids

    backend.fail_command = False
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    assert core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperMotionRejected, match='consumed'):
        core.command_position(
            0.3, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    with pytest.raises(GripperGatewayError, match='already been issued'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id, TOOL_REVISION)
    assert 'SECOND_MOVE_AUTH' not in core._used_authorization_ids
    assert len(backend.commands) == 1


def test_pre_send_failures_do_not_consume_valid_authorization():
    factory_calls = []

    def command_id_factory():
        factory_calls.append(True)
        if len(factory_calls) == 1:
            raise RuntimeError('id generation failed')
        return 'generated-after-retry'

    core, backend, unused_clock = make_core(
        command_id_factory=command_id_factory)
    core.refresh()
    with pytest.raises(ValueError, match='position'):
        core.command_position(
            -0.1, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert 'AUTH' not in core._used_authorization_ids
    assert factory_calls == []

    with pytest.raises(GripperMotionRejected, match='speed'):
        core.command_position(
            0.2, 0.0, 'AUTH', core.session_id, TOOL_REVISION)
    assert 'AUTH' not in core._used_authorization_ids
    assert factory_calls == []

    with pytest.raises(RuntimeError, match='id generation failed'):
        core.command_position(
            0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert 'AUTH' not in core._used_authorization_ids
    assert core._issued_command_ids == set()
    assert backend.commands == []

    command = core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    assert command.command_id == 'generated-after-retry'
    assert len(backend.commands) == 1


def test_stop_send_exception_requires_physical_stop_and_cannot_recover():
    core, backend, clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.fail_stop = True
    with pytest.raises(GripperGatewayError, match='stop send failed'):
        core.request_stop('operator stop', core.session_id)
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert backend.stop_calls == 1
    assert core._fault_stationary_verified is False
    assert core.physical_stop_required is True
    backend.fail_stop = False
    backend.moving = False
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id, TOOL_REVISION)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.request_stop('retry prohibited', core.session_id)
    assert backend.stop_calls == 1


def test_invalid_feedback_latches_fault():
    core, backend, unused_clock = make_core()
    backend.valid = False
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert 'invalid' in core.fault_reason


def test_ack_needs_stationary_samples_after_a_direct_fault():
    core, backend, clock = make_core(stable_samples=2)
    backend.valid = False
    core.refresh()
    backend.valid = True
    with pytest.raises(GripperMotionRejected, match='stationary'):
        core.acknowledge_local_fault('ACK', core.session_id)
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    assert core.acknowledge_local_fault('ACK', core.session_id)


def test_unhealthy_samples_never_count_as_stationary_evidence():
    core, backend, clock = make_core(stable_samples=2)
    backend.valid = False
    core.refresh()
    core.refresh()
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._fault_stationary_verified is False
    backend.valid = True
    core.refresh()
    clock.advance(0.2)
    core.refresh()
    assert core._fault_stationary_verified is True


def test_repeated_sequence_or_timestamp_cannot_accumulate_stationary():
    core, backend, unused_clock = make_core(stable_samples=2)
    backend.valid = False
    core.refresh()
    backend.valid = True
    core.refresh()
    assert core._stable_samples == 1
    accepted_snapshot = core.snapshot
    backend.sample_timestamp -= 0.01
    backend.auto_increment_timestamp = False
    rejected_snapshot = core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core._fault_stationary_verified is False
    assert core._stable_samples == 0
    assert rejected_snapshot.sample_timestamp <= (
        accepted_snapshot.sample_timestamp)
    assert core.snapshot is accepted_snapshot
    assert core._last_accepted_sequence == accepted_snapshot.sequence
    assert core._last_accepted_timestamp == (
        accepted_snapshot.sample_timestamp)

    sequence_core, sequence_backend, unused_clock = make_core(
        stable_samples=2)
    sequence_backend.valid = False
    sequence_core.refresh()
    sequence_backend.valid = True
    sequence_core.refresh()
    assert sequence_core._stable_samples == 1
    accepted_sequence_snapshot = sequence_core.snapshot
    sequence_backend.sequence -= 1
    sequence_backend.auto_increment_sequence = False
    rejected_sequence_snapshot = sequence_core.refresh()
    assert sequence_core._fault_stationary_verified is False
    assert sequence_core._stable_samples == 0
    assert rejected_sequence_snapshot.sequence <= (
        accepted_sequence_snapshot.sequence)
    assert sequence_core.snapshot is accepted_sequence_snapshot
    assert sequence_core._last_accepted_sequence == (
        accepted_sequence_snapshot.sequence)
    assert sequence_core._last_accepted_timestamp == (
        accepted_sequence_snapshot.sample_timestamp)


def test_non_monotonic_feedback_during_active_motion_escalates_once():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.sequence = 1
    backend.auto_increment_sequence = False
    core.refresh()
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    core.refresh()
    assert backend.stop_calls == 1


def test_unhealthy_sample_resets_prior_stationary_evidence():
    core, backend, unused_clock = make_core(stable_samples=2)
    backend.valid = False
    core.refresh()
    backend.valid = True
    core.refresh()
    assert core._stable_samples == 1
    backend.fault_code = 7
    core.refresh()
    assert core._stable_samples == 0
    assert core._fault_stationary_verified is False


def test_stationary_evidence_requires_position_tolerance_and_dwell():
    core, backend, clock = make_core(
        stable_samples=2,
        stationary_dwell_s=0.2,
        stationary_position_tolerance=0.01,
    )
    backend.valid = False
    core.refresh()
    backend.valid = True
    backend.position = 0.40
    core.refresh()
    assert core._stable_samples == 1

    clock.advance(0.2)
    backend.position = 0.42
    core.refresh()
    assert core._stable_samples == 0
    assert core._fault_stationary_verified is False

    backend.position = 0.42
    core.refresh()
    clock.advance(0.19)
    core.refresh()
    assert core._stable_samples == 2
    assert core._fault_stationary_verified is False
    clock.advance(0.02)
    core.refresh()
    assert core._fault_stationary_verified is True


def test_stop_timeout_requires_physical_stop_and_rejects_ack():
    core, backend, clock = make_core(stable_samples=3)
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    core.request_stop('operator stop', core.session_id)
    clock.advance(0.51)
    core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.physical_stop_required is True
    with pytest.raises(GripperMotionRejected, match='PHYSICAL'):
        core.acknowledge_local_fault('ACK', core.session_id)
    assert backend.stop_calls == 1


def test_state_query_failure_during_motion_stops_once_and_requires_physical():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.fail_read = True
    with pytest.raises(GripperGatewayError, match='state query failed'):
        core.refresh()
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    with pytest.raises(GripperGatewayError, match='state query failed'):
        core.refresh()
    assert backend.stop_calls == 1


def test_external_exception_text_cannot_reenter_motion():
    events = []
    string_calls = []

    class ReentrantError(Exception):
        def __str__(error):
            string_calls.append(True)
            core.command_position(
                0.4, 0.2, 'EVIL_AUTH', core.session_id, TOOL_REVISION)
            return 'untrusted exception detail'

    class ReentrantReadBackend(FakeBackend):
        def read_state(self):
            events.append('READ')
            raise ReentrantError()

        def command_position(self, position, speed, command_id):
            events.append('MOTION')
            return super().command_position(position, speed, command_id)

        def stop(self):
            events.append('STOP')
            return super().stop()

    backend = ReentrantReadBackend()
    core = GripperGatewayCore(
        backend,
        make_policy(),
        clock=FakeClock(),
        authorization_validator=lambda value, purpose, session_id: True,
    )
    with pytest.raises(GripperGatewayError, match='ReentrantError'):
        core.refresh()
    assert string_calls == []
    assert 'MOTION' not in events
    assert core.active_command is None
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert backend.stop_calls == 0


def test_active_numeric_feedback_is_rejected_without_reentry():
    calls = []
    core, backend, unused_clock = make_core()

    class ActiveFloat(float):
        def __float__(value):
            calls.append('float')
            core.close()
            return float.__float__(value)

    backend.position = ActiveFloat(0.5)
    with pytest.raises(GripperGatewayError, match='GripperCommandError'):
        core.refresh()
    assert calls == []
    assert backend.commands == []
    assert backend.close_count == 0
    assert core.state == GripperGatewayState.FAULT_LATCHED


@pytest.mark.parametrize('dwell', [0.0, float('nan'), float('inf')])
def test_policy_rejects_non_positive_or_non_finite_stationary_dwell(dwell):
    with pytest.raises(ValueError, match='stationary_dwell_s'):
        GripperGatewayPolicy(
            permit_motion=True,
            reviewed_tool_model=REVIEWED_TOOL_MODEL,
            reviewed_tool_revision=REVIEWED_TOOL_REVISION,
            reviewed_controller_identity=REVIEWED_CONTROLLER_IDENTITY,
            reviewed_transport_identity=REVIEWED_TRANSPORT_IDENTITY,
            reviewed_protocol_identity=REVIEWED_PROTOCOL_IDENTITY,
            state_max_age_s=0.5,
            command_timeout_s=1.0,
            stop_timeout_s=0.5,
            stable_samples_required=2,
            position_tolerance=0.02,
            stationary_position_tolerance=0.01,
            stationary_dwell_s=dwell,
        ).validate()


def test_non_finite_clock_latches_physical_stop_fail_closed():
    core, backend, clock = make_core()
    core.refresh()
    clock.now = float('nan')
    with pytest.raises(GripperGatewayError, match='clock'):
        core.refresh()
    assert core.state == GripperGatewayState.FAULT_LATCHED
    assert core.physical_stop_required is True
    assert backend.commands == []


def test_runtime_stationary_dwell_overflow_latches_physical_stop():
    core, backend, clock = make_core(stable_samples=2)
    clock.now = -1e308
    backend.valid = False
    core.refresh()
    backend.valid = True
    core.refresh()
    clock.now = 1e308
    core.refresh()
    assert core.physical_stop_required is True
    assert core._fault_stationary_verified is False


def test_close_active_command_closes_and_raises_unverified_stop_error():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    with pytest.raises(GripperGatewayError, match='PHYSICAL'):
        core.close()
    assert core.state == GripperGatewayState.CLOSED
    assert backend.stop_calls == 1
    assert backend.closed is True
    assert backend.close_count == 1
    assert core.active_command is None
    assert core.physical_stop_required is True
    core.close()
    assert backend.stop_calls == 1
    assert backend.close_count == 1


def test_close_while_stopping_does_not_retry_unknown_stop():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    core.request_stop('operator stop', core.session_id)
    with pytest.raises(GripperGatewayError, match='not verified'):
        core.close()
    assert backend.stop_calls == 1
    assert backend.close_count == 1
    assert core.state == GripperGatewayState.CLOSED
    assert core.active_command is None
    assert core.physical_stop_required is True


def test_close_aggregates_stop_and_backend_close_errors_then_is_idempotent():
    core, backend, unused_clock = make_core()
    core.refresh()
    core.command_position(
        0.2, 0.2, 'AUTH', core.session_id, TOOL_REVISION)
    backend.fail_stop = True
    backend.fail_close = True
    try:
        core.close()
    except GripperGatewayError as error:
        detail = str(error)
    else:
        raise AssertionError('close must report unresolved safety errors')
    assert 'STOP failed' in detail
    assert 'backend close failed' in detail
    assert core.state == GripperGatewayState.CLOSED
    assert core.active_command is None
    assert core.physical_stop_required is True
    assert backend.stop_calls == 1
    assert backend.close_count == 1
    assert backend.closed is False
    with pytest.raises(GripperGatewayError, match='closed'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id,
            TOOL_REVISION)
    with pytest.raises(GripperGatewayError, match='backend close failed'):
        core.close()
    assert backend.close_count == 2
    assert backend.closed is False
    backend.fail_close = False
    core.close()
    assert backend.stop_calls == 1
    assert backend.close_count == 3
    assert backend.closed is True
    core.close()
    assert backend.close_count == 3
    with pytest.raises(GripperGatewayError, match='closed'):
        core.command_position(
            0.3, 0.2, 'SECOND_MOVE_AUTH', core.session_id,
            TOOL_REVISION)
    assert core.physical_stop_required is True
