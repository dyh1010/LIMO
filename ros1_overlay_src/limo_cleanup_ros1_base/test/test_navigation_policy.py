import json
import math
from pathlib import Path
import sys
import threading

import pytest


PACKAGE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / 'src'))

from limo_cleanup_ros1_base.navigation_health import (  # noqa: E402
    navigation_health_ready,
    received_sample_is_fresh,
    ScanWindow,
    scan_contract_ready,
    timestamp_is_fresh,
    TransformChainWindow,
    transform_values_ready,
)
from limo_cleanup_ros1_base.navigation_policy import (  # noqa: E402
    AtomicNavigationProtocol,
    GoalGenerationGate,
    PoseValues,
    parse_bridge_command,
    validate_navigation_goal,
)


VALID_GOAL = PoseValues(
    frame_id='map',
    position_x=1.0,
    position_y=2.0,
    position_z=0.0,
    orientation_x=0.0,
    orientation_y=0.0,
    orientation_z=0.0,
    orientation_w=1.0,
)
TEST_ACTIVE_MAP_ID = 'v1_frozen_map'


def _dispatch(epoch, nonce, x=1.0):
    return parse_bridge_command(json.dumps({
        'protocol': 'cleanup_navigation_bridge/v3',
        'operation': 'dispatch_goal',
        'epoch': epoch,
        'nonce': nonce,
        'map_id': TEST_ACTIVE_MAP_ID,
        'goal': {'frame_id': 'map', 'x': x, 'y': 2.0, 'yaw': 0.0},
    }))


def _cancel(epoch):
    return parse_bridge_command(json.dumps({
        'protocol': 'cleanup_navigation_bridge/v3',
        'operation': 'cancel',
        'epoch': epoch,
    }))


def test_atomic_protocol_rejects_replay_and_cancelled_delayed_goal():
    nonces = iter([
        'nonce000000000001',
        'nonce000000000002',
        'nonce000000000003',
        'nonce000000000004',
        'nonce000000000005',
    ])
    protocol = AtomicNavigationProtocol(nonce_factory=lambda: next(nonces))
    command = _dispatch(1, protocol.nonce)
    assert protocol.accept(command, True, TEST_ACTIVE_MAP_ID) == 'accepted'
    assert protocol.accept(command, True, TEST_ACTIVE_MAP_ID) == 'duplicate'
    assert protocol.accept(_cancel(2), True) == 'cancelled'
    with pytest.raises(RuntimeError):
        protocol.accept(command, True, TEST_ACTIVE_MAP_ID)
    assert protocol.state == 'rejected'


def test_health_loss_cancels_authority_and_rotates_nonce():
    protocol = AtomicNavigationProtocol()
    command = _dispatch(1, protocol.nonce)
    assert protocol.accept(command, True, TEST_ACTIVE_MAP_ID) == 'accepted'
    active_nonce = protocol.nonce
    assert protocol.set_navigation_ready(False)
    assert protocol.state == 'unavailable'
    assert protocol.active_epoch is None
    assert protocol.nonce != active_nonce
    status = json.loads(protocol.status_payload(False, False, False))
    assert status['protocol'] == 'cleanup_navigation_bridge/v3'
    assert status['state'] == 'unavailable'
    assert status['server_ready'] is False
    assert status['scan_fresh'] is False
    assert status['tf_ready'] is False


def test_scan_and_tf_freshness_are_strict_at_timeout():
    assert timestamp_is_fresh(10.0, 10.499999, 0.5)
    assert not timestamp_is_fresh(10.0, 10.5, 0.5)
    assert not timestamp_is_fresh(10.2, 10.0, 0.5)
    assert received_sample_is_fresh(20.0, 30.0, 20.4, 30.4, 0.5)
    assert not received_sample_is_fresh(20.0, 30.0, 20.5, 30.4, 0.5)
    assert navigation_health_ready(True, True, True)
    assert not navigation_health_ready(True, False, True)
    assert not navigation_health_ready(True, True, False)


def test_scan_rate_range_and_tf_numeric_contracts_fail_closed():
    receipts = [index / 6 for index in range(10)]
    ranges = [0.5] * 360
    angle_min = math.radians(-100.0)
    angle_max = math.radians(100.0)
    increment = (angle_max - angle_min) / 359
    assert scan_contract_ready(
        ranges, 0.02, 16.0, angle_min, angle_max, increment, receipts)
    assert not scan_contract_ready(
        [0.5], 0.02, 16.0, angle_min, angle_max, increment, receipts)
    assert not scan_contract_ready(
        [float('nan')] * 360, 0.02, 16.0,
        angle_min, angle_max, increment, receipts)
    assert not scan_contract_ready(
        ranges, 0.01, 16.0, angle_min, angle_max, increment, receipts)
    assert not scan_contract_ready(
        ranges, 0.02, 16.0, angle_min, angle_max, increment,
        [index * 0.1 for index in range(10)])
    assert not scan_contract_ready(
        ranges, 0.02, 16.0, -math.pi, math.pi,
        2 * math.pi / 359, receipts)
    assert transform_values_ready((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    assert not transform_values_ready(
        (float('nan'), 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    assert not transform_values_ready(
        (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.5))


def _add_scan(window, index, interval=1 / 6, ranges=None):
    scan_ranges = ranges if ranges is not None else [0.5] * 360
    receipt = index * interval
    source = 100.0 + receipt
    return window.add(
        frame_id='laser_link',
        expected_frame='laser_link',
        ranges=scan_ranges,
        range_min=0.02,
        range_max=16.0,
        angle_min=math.radians(-100.0),
        angle_max=math.radians(100.0),
        angle_increment=math.radians(200.0) / 359,
        source_stamp=source,
        receipt_time=receipt,
        ros_now=source,
        timeout=0.5,
        future_tolerance=0.1,
    )


def test_scan_window_rejects_one_or_nine_and_accepts_tenth_sample():
    window = ScanWindow()
    assert not _add_scan(window, 0)
    for index in range(1, 9):
        assert not _add_scan(window, index)
    assert not window.ready(8 / 6, 100.0 + 8 / 6, 0.5)
    assert _add_scan(window, 9)
    assert window.ready(9 / 6, 100.0 + 9 / 6, 0.5)


def test_bad_scan_clears_window_and_requires_ten_new_samples():
    window = ScanWindow()
    for index in range(9):
        assert not _add_scan(window, index)
    assert not _add_scan(window, 9, ranges=[float('nan')] * 360)
    for offset in range(1, 10):
        assert not _add_scan(window, 9 + offset)
    assert _add_scan(window, 19)


@pytest.mark.parametrize('interval,expected', [
    (1 / 7.2, True),
    (1 / 4.8, True),
    (1 / 7.2 - 1e-6, False),
    (1 / 4.8 + 1e-6, False),
])
def test_scan_window_interval_boundaries(interval, expected):
    window = ScanWindow()
    result = False
    for index in range(10):
        result = _add_scan(window, index, interval=interval)
    assert result is expected


def test_scan_window_rejects_stamp_rollback_future_and_sparse_finite_data():
    window = ScanWindow()
    assert not _add_scan(window, 0)
    assert not window.add(
        frame_id='laser_link', expected_frame='laser_link',
        ranges=[0.5] * 360, range_min=0.02, range_max=16.0,
        angle_min=math.radians(-100.0), angle_max=math.radians(100.0),
        angle_increment=math.radians(200.0) / 359,
        source_stamp=99.0, receipt_time=1 / 6, ros_now=100.0,
        timeout=0.5, future_tolerance=0.1)
    assert not window.add(
        frame_id='laser_link', expected_frame='laser_link',
        ranges=[0.5] * 360, range_min=0.02, range_max=16.0,
        angle_min=math.radians(-100.0), angle_max=math.radians(100.0),
        angle_increment=math.radians(200.0) / 359,
        source_stamp=101.0, receipt_time=2 / 6, ros_now=100.0,
        timeout=0.5, future_tolerance=0.1)
    sparse = [0.5] * 17 + [float('inf')] * 343
    assert not _add_scan(window, 3, ranges=sparse)


def test_tf_chain_requires_each_monotonic_fresh_normalized_segment():
    chain = TransformChainWindow()
    for index, segment in enumerate(chain.REQUIRED_SEGMENTS):
        assert chain.update(
            segment,
            100.0 + index * 0.01,
            10.0 + index * 0.01,
            100.0 + index * 0.01,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
            0.5,
            0.1,
        )
    assert chain.ready(10.03, 100.03, 0.5, 0.1)
    assert not chain.update(
        'map_to_odom', 99.99, 10.04, 100.04,
        (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.5, 0.1)
    assert not chain.ready(10.04, 100.04, 0.5, 0.1)


def test_tf_future_boundary_and_stopped_publisher_do_not_extend_freshness():
    chain = TransformChainWindow()
    for segment in chain.REQUIRED_SEGMENTS:
        assert chain.update(
            segment, 100.10, 20.0, 100.0,
            (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.5, 0.1)
    assert chain.ready(20.0, 100.0, 0.5, 0.1)
    assert not chain.ready(20.5, 100.5, 0.5, 0.1)


def test_only_finite_normalized_map_goals_are_allowed():
    validate_navigation_goal(VALID_GOAL)
    with pytest.raises(ValueError):
        validate_navigation_goal(PoseValues(
            **{**VALID_GOAL.__dict__, 'frame_id': 'odom'}))
    with pytest.raises(ValueError):
        validate_navigation_goal(PoseValues(
            **{**VALID_GOAL.__dict__, 'position_x': math.nan}))
    with pytest.raises(ValueError):
        validate_navigation_goal(PoseValues(
            **{**VALID_GOAL.__dict__, 'orientation_w': 0.0}))


def test_command_parser_rejects_duplicate_keys_recursively_and_bad_types():
    malicious = (
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"cancel","operation":"dispatch_goal","epoch":1}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"cancel","epoch":1,"epoch":2}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"dispatch_goal","epoch":1,'
        '"nonce":"nonce000000000001","map_id":"v1_frozen_map",'
        '"goal":{"frame_id":"map","x":1.0,"x":2.0,'
        '"y":2.0,"yaw":0.0}}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":[],"epoch":1}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"dispatch_goal","epoch":1,'
        '"nonce":"nonce000000000001","map_id":"v1_frozen_map",'
        '"goal":[]}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"dispatch_goal","epoch":1,'
        '"nonce":"nonce000000000001","map_id":"v1_frozen_map",'
        '"goal":{"frame_id":{},"x":1.0,"y":2.0,"yaw":0.0}}',
        '{"protocol":"cleanup_navigation_bridge/v3",'
        '"operation":"dispatch_goal","epoch":1,'
        '"nonce":"nonce000000000001","map_id":"v1_frozen_map",'
        '"goal":{"frame_id":"map","x":NaN,"y":2.0,"yaw":0.0}}',
    )
    for payload in malicious:
        with pytest.raises(ValueError):
            parse_bridge_command(payload)


def test_command_parser_wraps_deep_recursion_as_value_error():
    with pytest.raises(ValueError):
        parse_bridge_command('[' * 2000 + '0' + ']' * 2000)


def test_cancel_invalidates_a_queued_goal_before_send_deterministically():
    gate = GoalGenerationGate()
    reserved = gate.reserve()
    ready_to_commit = threading.Barrier(2)
    cancel_complete = threading.Event()
    sent = []
    committed = []

    def queued_send():
        ready_to_commit.wait()
        cancel_complete.wait(timeout=2.0)
        committed.append(gate.commit(reserved, lambda: sent.append('sent')))

    thread = threading.Thread(target=queued_send)
    thread.start()
    ready_to_commit.wait()
    gate.invalidate(lambda: sent.append('cancelled'))
    cancel_complete.set()
    thread.join(timeout=2.0)
    assert committed == [False]
    assert sent == ['cancelled']


def test_old_result_callback_is_rejected_after_fault_generation_change():
    gate = GoalGenerationGate()
    generation = gate.reserve()
    assert gate.is_current(generation)
    gate.invalidate()
    assert not gate.is_current(generation)
