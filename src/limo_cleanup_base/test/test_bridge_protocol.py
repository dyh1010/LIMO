from pathlib import Path
import multiprocessing
import threading

import pytest

from limo_cleanup_base.bridge_protocol import (
    BridgeStatus,
    CancelRetryPolicy,
    EpochStore,
    NavigationAuthorizationPolicy,
    build_cancel_command,
    build_dispatch_command,
    parse_bridge_status,
)
from limo_cleanup_base.navigation_intent_policy import MapWaypoint


def _allocate_epoch(path):
    return EpochStore(path).allocate()


def test_epoch_store_is_persistent_and_monotonic(tmp_path: Path):
    path = tmp_path / 'epoch'
    assert EpochStore(str(path)).allocate() == 1
    assert EpochStore(str(path)).allocate() == 2


def test_epoch_store_concurrent_allocations_have_no_duplicates(tmp_path: Path):
    path = str(tmp_path / 'concurrent_epoch')
    context = multiprocessing.get_context('fork')
    with context.Pool(processes=4) as pool:
        allocated = pool.map(_allocate_epoch, [path] * 32)
    assert sorted(allocated) == list(range(1, 33))


def test_command_builders_keep_voice_schema_out_of_internal_protocol():
    cancel = build_cancel_command(1)
    assert 'cleanup_navigation_bridge/v3' in cancel
    assert 'request_safe_stop' not in cancel
    dispatch = build_dispatch_command(
        2,
        'nonce000000000001',
        MapWaypoint(
            map_id='v1',
            target_id='trash_bin_staging',
            frame_id='map',
            x=1.0,
            y=2.0,
            yaw=0.0,
        ),
    )
    assert 'dispatch_goal' in dispatch
    assert 'trash_bin_staging' not in dispatch


def test_bridge_status_rejects_duplicate_keys_and_unhashable_state_types():
    valid_tail = (
        '"epoch":1,"nonce":"nonce000000000001",'
        '"server_ready":true,"scan_fresh":true,"tf_ready":true')
    malicious = (
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"state":"ready","state":"active",' + valid_tail + '}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"protocol":"cleanup_navigation_bridge/v3",'
        '"state":"ready",' + valid_tail + '}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"state":"ready","epoch":1,"epoch":2,'
        '"nonce":"nonce000000000001",'
        '"server_ready":true,"scan_fresh":true,"tf_ready":true}',
    )
    for payload in malicious:
        with pytest.raises(ValueError):
            parse_bridge_status(payload)
    for value in ('[]', '{}', 'true', '1'):
        with pytest.raises(ValueError):
            parse_bridge_status(
                '{"protocol":"cleanup_navigation_bridge/v3",'
                '"state":' + value + ',' + valid_tail + '}')


def test_bridge_status_rejects_nonfinite_json_constants_as_value_error():
    with pytest.raises(ValueError):
        parse_bridge_status(
            '{"protocol":"cleanup_navigation_bridge/v3",'
            '"state":"ready","epoch":NaN,'
            '"nonce":"nonce000000000001",'
            '"server_ready":true,"scan_fresh":true,"tf_ready":true}')


def test_bridge_status_wraps_deep_recursion_as_value_error():
    with pytest.raises(ValueError):
        parse_bridge_status('[' * 2000 + '0' + ']' * 2000)


def test_cancel_retries_are_bounded_until_nonactive_ack():
    retry = CancelRetryPolicy(interval=0.05, timeout=0.50)
    retry.start(8, 'cancel-8', 1.0)
    assert retry.next_payload(1.049999) is None
    assert retry.next_payload(1.05) == 'cancel-8'
    assert retry.next_payload(1.10) == 'cancel-8'
    assert not retry.acknowledge(_status(
        'active', 8, 'nonce000000000008'))
    assert retry.active
    assert retry.acknowledge(_status(
        'stopped', 8, 'nonce000000000009'))
    assert not retry.active
    retry.start(9, 'cancel-9', 2.0)
    assert retry.next_payload(2.499999) == 'cancel-9'
    assert retry.next_payload(2.5) is None
    assert retry.active
    assert retry.retry_exhausted
    assert not retry.acknowledge(_status(
        'stopped', 10, 'nonce000000000010'))
    assert retry.active
    assert retry.acknowledge(_status(
        'stopped', 9, 'nonce000000000009'))
    assert not retry.active


def test_cancel_barrier_survives_old_status_and_concurrent_retry_timeout():
    retry = CancelRetryPolicy(interval=0.05, timeout=0.50)
    retry.start(41, 'cancel-41', 10.0)
    entered = threading.Barrier(3)
    release = threading.Event()
    dispatch_allowed = []

    def old_status_callback():
        entered.wait()
        release.wait(timeout=2.0)
        retry.acknowledge(_status(
            'stopped', 40, 'nonce000000000040'))

    def timeout_callback():
        entered.wait()
        release.wait(timeout=2.0)
        retry.next_payload(10.50)

    threads = [
        threading.Thread(target=old_status_callback),
        threading.Thread(target=timeout_callback),
    ]
    for thread in threads:
        thread.start()
    entered.wait()
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)
    dispatch_allowed.append(not retry.active)
    assert dispatch_allowed == [False]
    assert retry.retry_exhausted
    assert retry.acknowledge(_status(
        'preempted', 41, 'nonce000000000041'))
    assert not retry.active


def test_cancel_pending_atomically_prevents_new_epoch_or_goal_allocation():
    retry = CancelRetryPolicy(interval=0.05, timeout=0.50)
    retry.start(51, 'cancel-51', 30.0)
    entered = threading.Barrier(3)
    release = threading.Event()
    allocated = []
    results = []

    def navigate_callback(nonce):
        entered.wait()
        release.wait(timeout=2.0)
        results.append(retry.run_if_clear(
            lambda: allocated.append(nonce) or nonce))

    threads = [
        threading.Thread(target=navigate_callback, args=('nonce-a',)),
        threading.Thread(target=navigate_callback, args=('nonce-b',)),
    ]
    for thread in threads:
        thread.start()
    entered.wait()
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)
    assert results == [(False, None), (False, None)]
    assert allocated == []
    assert retry.active


def _status(state, epoch, nonce, healthy=True):
    return BridgeStatus(
        state=state,
        epoch=epoch,
        nonce=nonce,
        server_ready=healthy,
        scan_fresh=healthy,
        tf_ready=healthy,
    )


def test_authorization_requires_fresh_matching_active_epoch():
    policy = NavigationAuthorizationPolicy()
    ready_nonce = 'nonce000000000001'
    policy.update(_status('stopped', 1, ready_nonce), 1.0)
    policy.dispatch(2, ready_nonce, 1.05)
    assert not policy.authorization(1.1, 0.25)
    policy.update(_status('active', 2, 'nonce000000000002'), 1.1)
    assert policy.authorization(1.349, 0.25)
    assert not policy.pending_expired(1.349, 0.25)
    assert policy.pending_expired(1.35, 0.25)
    assert policy.fault_latched
    assert not policy.update(
        _status('active', 2, 'nonce000000000002'), 1.36)
    assert not policy.authorization(1.37, 0.25)
    recovery_nonce = 'nonce000000000003'
    assert policy.update(_status('ready', 2, recovery_nonce), 1.38)
    assert policy.fault_latched
    assert not policy.authorization(1.39, 0.25)
    with pytest.raises(RuntimeError):
        policy.dispatch(3, ready_nonce, 1.40)
    policy.dispatch(3, recovery_nonce, 1.40)
    assert not policy.fault_latched
    policy.update(_status('active', 3, 'nonce000000000004'), 1.41)
    assert policy.authorization(1.42, 0.25)


def test_authorization_requires_scan_and_tf_health():
    for scan_fresh, tf_ready in ((False, True), (True, False)):
        policy = NavigationAuthorizationPolicy()
        ready_nonce = 'nonce000000000006'
        policy.update(_status('ready', 6, ready_nonce), 2.0)
        policy.dispatch(7, ready_nonce, 2.001)
        assert not policy.update(BridgeStatus(
            state='active', epoch=7, nonce='nonce000000000007',
            server_ready=True, scan_fresh=scan_fresh,
            tf_ready=tf_ready), 2.01)
        assert not policy.authorization(2.02, 0.25)
        assert policy.fault_latched


def test_fault_rejects_old_status_health_recovery_and_reused_nonce():
    policy = NavigationAuthorizationPolicy()
    first_nonce = 'nonce000000000101'
    active_nonce = 'nonce000000000102'
    policy.update(_status('ready', 10, first_nonce), 5.0)
    policy.dispatch(11, first_nonce, 5.01)
    policy.update(_status('active', 11, active_nonce), 5.02)
    assert policy.authorization(5.03, 0.25)
    assert not policy.update(
        _status('unavailable', 11, 'nonce000000000103', healthy=False),
        5.04)
    assert policy.fault_latched
    for old in (
            _status('active', 11, active_nonce),
            _status('ready', 10, first_nonce)):
        assert not policy.update(old, 5.05)
        assert not policy.authorization(5.06, 0.25)
    recovery_nonce = 'nonce000000000104'
    assert policy.update(_status('ready', 11, recovery_nonce), 5.07)
    assert policy.fault_latched
    policy.dispatch(12, recovery_nonce, 5.08)
    assert policy.update(_status('active', 12, 'nonce000000000105'), 5.09)
    assert policy.authorization(5.10, 0.25)
    assert not policy.update(_status('ready', 13, active_nonce), 5.11)
    assert policy.fault_latched


def test_concurrent_reused_nonce_epoch_is_sticky_faulted():
    policy = NavigationAuthorizationPolicy()
    barrier = threading.Barrier(3)
    outcomes = []

    def update(epoch):
        barrier.wait()
        outcomes.append(policy.update(
            _status('ready', epoch, 'nonce000000000900'), 20.0 + epoch))

    threads = [threading.Thread(target=update, args=(epoch,))
               for epoch in (20, 21)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2.0)
    assert sorted(outcomes) == [False, True]
    assert policy.fault_latched


def test_total_goal_deadline_latches_fault_at_boundary():
    policy = NavigationAuthorizationPolicy()
    nonce = 'nonce000000000301'
    policy.update(_status('ready', 30, nonce), 30.0)
    policy.dispatch(31, nonce, 30.1)
    policy.update(_status('active', 31, 'nonce000000000302'), 30.11)
    assert not policy.goal_expired(40.099999, 10.0)
    assert policy.goal_expired(40.1, 10.0)
    assert policy.fault_latched
    assert not policy.authorization(40.1, 0.25)
