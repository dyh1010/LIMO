"""Pure-software contracts for the isolated ROS1 STOP endpoint ingress."""

import pytest

from limo_cleanup_voice.ros1_noetic_adapter import Ros1NoeticAdapterCore
from limo_cleanup_voice.ros1_stop_endpoint_ingress import (
    ENDPOINT_SOURCE,
    REJECTED_PARTIAL_SOURCE,
    Ros1StopEndpointIngressCore,
)


def make_ingress():
    core = Ros1NoeticAdapterCore(
        process_instance_id='voice-stop-ingress-test',
        monotonic_ns=lambda: 1_000_000_000,
        wall_time_ns=lambda: 2_000_000_000,
    )
    return core, Ros1StopEndpointIngressCore(core)


def test_complete_endpoint_stop_creates_internal_event_only():
    core, ingress = make_ingress()

    decision = ingress.observe(
        'stream-stop-001', 0, ENDPOINT_SOURCE, '停下',
        now_ns=1_000_000_000)

    assert decision.state == 'priority_stop_internal'
    assert decision.stop_event['intent'] == 'stop_task'
    assert decision.stop_event['actual_publish_count'] == 0
    assert [item['actual_published'] for item in
            decision.stop_event['repeat_attempts']] == [False] * 3
    assert core.has_pending is False


def test_partial_stop_is_rejected_without_touching_adapter_state():
    core, ingress = make_ingress()

    decision = ingress.observe(
        'stream-partial-001', 0, REJECTED_PARTIAL_SOURCE, '停下')

    assert decision.state == 'ignored_partial'
    assert decision.stop_event is None
    assert core.stop_epoch == 0
    assert core.has_pending is False


@pytest.mark.parametrize('text', [
    '小莫小莫到垃圾桶旁边去',
    '小莫小莫捡矿泉水瓶',
    '确认',
    '取消',
])
def test_ordinary_or_dialogue_text_cannot_create_pending(text):
    core, ingress = make_ingress()

    decision = ingress.observe(
        'stream-ordinary-001', 0, ENDPOINT_SOURCE, text)

    assert decision.state == 'ignored_non_stop'
    assert decision.actual_publish_count == 0
    assert decision.production_publish_count == 0
    assert decision.stop_event is None
    assert core.has_pending is False
    assert core.stop_epoch == 0


@pytest.mark.parametrize('first, second', [
    ('不要', '停止'),
    ('别管那个瓶子', '停止'),
    ('字幕显示', '紧急停止'),
    ('刚刚有人说', '停下'),
])
def test_same_stream_context_blocks_split_non_command(first, second):
    core, ingress = make_ingress()

    initial = ingress.observe(
        'stream-context-001', 0, ENDPOINT_SOURCE, first)
    later = ingress.observe(
        'stream-context-001', 1, ENDPOINT_SOURCE, second)

    assert initial.state == 'ignored_non_stop'
    assert later.state == 'ignored_non_stop'
    assert core.stop_epoch == 0
    assert core.has_pending is False


def test_stream_context_isolated_and_reset_is_explicit():
    core, ingress = make_ingress()
    ingress.observe('stream-a-001', 0, ENDPOINT_SOURCE, '不要')

    stopped = ingress.observe(
        'stream-b-001', 0, ENDPOINT_SOURCE, '停下',
        now_ns=1_000_000_000)
    ingress.reset_stream('stream-a-001')
    after_reset = ingress.observe(
        'stream-a-001', 0, ENDPOINT_SOURCE, '停下',
        now_ns=2_000_000_000)

    assert stopped.state == 'priority_stop_internal'
    assert after_reset.state == 'priority_stop_internal'
    assert core.stop_epoch == 2


def test_duplicate_or_out_of_order_endpoint_is_fail_closed():
    core, ingress = make_ingress()
    ingress.observe('stream-order-001', 0, ENDPOINT_SOURCE, '普通对话')

    duplicate = ingress.observe(
        'stream-order-001', 0, ENDPOINT_SOURCE, '停下')
    skipped = ingress.observe(
        'stream-order-001', 2, ENDPOINT_SOURCE, '停下')

    assert duplicate.state == 'rejected_sequence'
    assert skipped.state == 'rejected_sequence'
    assert core.stop_epoch == 0


def test_repeated_complete_stop_exposes_adapter_debounce_state():
    core, ingress = make_ingress()
    first = ingress.observe(
        'stream-repeat-001', 0, ENDPOINT_SOURCE, '停下',
        now_ns=1_000_000_000)
    repeated = ingress.observe(
        'stream-repeat-001', 1, ENDPOINT_SOURCE, '停下',
        now_ns=1_100_000_000)

    assert first.state == 'priority_stop_internal'
    assert repeated.state == 'stop_debounced'
    assert repeated.stop_event['event_id'] == first.stop_event['event_id']
    assert core.stop_epoch == 1


def test_stream_capacity_fails_closed_without_eviction_or_trigger():
    core = Ros1NoeticAdapterCore(
        process_instance_id='voice-stop-capacity-test')
    ingress = Ros1StopEndpointIngressCore(core, max_streams=1)
    first = ingress.observe(
        'stream-capacity-a', 0, ENDPOINT_SOURCE, '普通对话')

    rejected = ingress.observe(
        'stream-capacity-b', 0, ENDPOINT_SOURCE, '停下')

    assert first.state == 'ignored_non_stop'
    assert rejected.state == 'rejected_capacity'
    assert rejected.stop_event is None
    assert core.stop_epoch == 0
    assert core.has_pending is False


@pytest.mark.parametrize('source', ['', 'endpoint', None, True])
def test_unreviewed_source_never_triggers(source):
    core, ingress = make_ingress()

    decision = ingress.observe(
        'stream-source-001', 0, source, '停下')

    assert decision.state == 'ignored_source'
    assert core.stop_epoch == 0


@pytest.mark.parametrize('stream_id, index, text', [
    ('', 0, '停下'),
    ('bad id', 0, '停下'),
    ('stream-input-001', -1, '停下'),
    ('stream-input-001', True, '停下'),
    ('stream-input-001', 0, ''),
    ('stream-input-001', 0, 'x' * 257),
])
def test_invalid_wire_input_is_rejected(stream_id, index, text):
    _, ingress = make_ingress()

    with pytest.raises(ValueError):
        ingress.observe(stream_id, index, ENDPOINT_SOURCE, text)


@pytest.mark.parametrize('segments, streams', [
    (0, 64),
    (33, 64),
    (True, 64),
    (8, 0),
    (8, 1025),
    (8, False),
])
def test_invalid_capacity_configuration_is_rejected(segments, streams):
    core = Ros1NoeticAdapterCore(
        process_instance_id='voice-stop-config-test')

    with pytest.raises(ValueError):
        Ros1StopEndpointIngressCore(
            core, max_context_segments=segments, max_streams=streams)
