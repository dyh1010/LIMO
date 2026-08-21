"""Pure software tests for the fail-closed ROS1/Noetic adapter core."""

import json
from pathlib import Path

import pytest

from limo_cleanup_voice.ros1_noetic_adapter import (
    Ros1AdapterConfig,
    Ros1NoeticAdapterCore,
)
from limo_cleanup_voice.ros1_audio_input import (
    AudioInputContractError,
    Ros1AudioInputConfig,
)
from limo_cleanup_voice.voice_contract import (
    parse_stop_broadcast,
    stop_ack_payload,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _core():
    return Ros1NoeticAdapterCore(
        process_instance_id='voice-ros1-process-test0001',
        monotonic_ns=lambda: 1_000_000_000,
        wall_time_ns=lambda: 2_000_000_000,
    )


@pytest.mark.parametrize('process_instance_id', (
    '',
    '   ',
    True,
    False,
    'short',
    'x' * 129,
    'voice process invalid',
    'voice/process/invalid',
))
def test_constructor_rejects_invalid_process_instance_id(
        process_instance_id):
    with pytest.raises(ValueError):
        Ros1NoeticAdapterCore(process_instance_id=process_instance_id)


def test_default_process_instance_id_round_trips_through_stop_wire_schema():
    core = Ros1NoeticAdapterCore(
        monotonic_ns=lambda: 1_000_000_000,
        wall_time_ns=lambda: 2_000_000_000,
    )

    stopped = core.process_transcript('停下', now_ns=100)

    assert all(
        parse_stop_broadcast(json.dumps(attempt['payload']))[
            'process_instance_id'] == core.process_instance_id
        for attempt in stopped.stop_event['repeat_attempts'])


@pytest.mark.parametrize('field, value', (
    ('profile', 'production_noetic'),
    ('allow_ros_publish', True),
    ('allow_production_outputs', True),
))
def test_config_rejects_every_live_or_production_surface(field, value):
    values = {field: value}

    with pytest.raises(ValueError):
        Ros1AdapterConfig(**values).validate()


@pytest.mark.parametrize('value', (False, 0, 1, 'true', None))
def test_config_rejects_disabled_or_non_boolean_wake_gate(value):
    with pytest.raises(ValueError):
        Ros1AdapterConfig(require_wake_word=value).validate()


@pytest.mark.parametrize('sources', (
    ('untrusted_stop_observer',),
    ('cleanup_ros1_stop_gate', 'untrusted_stop_observer'),
    ['cleanup_ros1_stop_gate'],
))
def test_config_locks_exact_stop_ack_source_owner(sources):
    with pytest.raises(ValueError):
        Ros1AdapterConfig(stop_ack_sources=sources).validate()


def test_config_rejects_empty_stop_ack_source_owner():
    with pytest.raises(ValueError):
        Ros1AdapterConfig(stop_ack_sources=()).validate()


@pytest.mark.parametrize('tolerance_ns', (1, 4_999_999_999, 5_000_000_001))
def test_config_locks_stop_ack_future_wall_tolerance(tolerance_ns):
    with pytest.raises(ValueError):
        Ros1AdapterConfig(
            stop_ack_future_wall_tolerance_ns=tolerance_ns,
        ).validate()


def test_unwoken_ordinary_intent_never_creates_pending_or_output():
    core = _core()

    decision = core.process_transcript('到垃圾桶旁边去')

    assert decision.intent == 'ignored'
    assert core.has_pending is False
    assert decision.actual_publish_count == 0
    assert decision.production_publish_count == 0
    assert decision.mock_output_plan is None


def test_core_exposes_reviewed_inert_audio_plan_only(tmp_path):
    core = _core()

    plan = core.plan_audio_input(tmp_path, 'adapter_probe', 8)

    assert plan.capture_argv[:4] == ('arecord', '-D', 'hw:0,0', '-q')
    assert plan.capture_argv[4:12] == (
        '-f', 'S16_LE', '-r', '48000', '-c', '2', '-d', '8')
    assert plan.conversion_argv[-2:] == ('remix', '1')
    assert plan.microphone_opened is False
    assert plan.actual_process_count == 0
    assert plan.actual_publish_count == 0


def test_core_rejects_unreviewed_audio_config_at_construction():
    with pytest.raises(AudioInputContractError):
        Ros1NoeticAdapterCore(
            audio_input_config=Ros1AudioInputConfig(
                capture_device='plughw:0,0'))


def test_wake_confirmation_creates_mock_plan_but_publishes_nothing():
    core = _core()

    wake = core.process_transcript('小莫小莫', now_ns=1)
    pending = core.process_transcript('处理一下那个瓶子', now_ns=2)
    confirmed = core.process_transcript('确认', now_ns=3)

    assert wake.state == 'wake_armed'
    assert pending.state == 'pending_confirmation'
    assert confirmed.state == 'mock_confirmed'
    assert confirmed.mock_output_plan['topic'].startswith('/voice_mock/')
    assert confirmed.mock_output_plan['actual_published'] is False
    assert confirmed.actual_publish_count == 0
    assert confirmed.production_publish_count == 0


def test_complete_wake_phrase_is_required_before_ordinary_pending():
    core = _core()

    near_wake = core.process_transcript(
        '小魔小魔，处理一下那个瓶子', now_ns=1)
    unwoken = core.process_transcript('处理一下那个瓶子', now_ns=2)
    complete = core.process_transcript(
        '小莫小莫，处理一下那个瓶子', now_ns=3)

    assert near_wake.intent == 'ignored'
    assert unwoken.intent == 'ignored'
    assert complete.state == 'pending_confirmation'
    assert complete.requires_confirmation is True
    assert complete.actual_publish_count == 0


def test_observed_vosk_wake_alias_is_exact_prefix_mock_only():
    core = _core()

    wake = core.process_transcript('小沫 小沫', now_ns=1)
    pending = core.process_transcript('捡瓶子', now_ns=2)

    assert wake.state == 'wake_armed'
    assert pending.state == 'pending_confirmation'
    assert pending.intent == 'start_cleanup'
    assert pending.actual_publish_count == 0
    assert pending.production_publish_count == 0


@pytest.mark.parametrize('text', (
    '小沫小沫斯科，捡瓶子',
    '电视播放小沫小沫捡瓶子',
    '别人喊小沫小沫捡瓶子',
    '请不要说小沫小沫然后捡瓶子',
    '捡瓶子，小沫小沫',
))
def test_observed_vosk_wake_alias_is_not_substring_or_quotation(text):
    core = _core()

    decision = core.process_transcript(text, now_ns=1)

    assert decision.intent == 'ignored'
    assert core.has_pending is False
    assert decision.actual_publish_count == 0


def test_cancel_and_timeout_never_create_mock_or_production_output():
    core = _core()
    core.process_transcript('小莫小莫', now_ns=1)
    core.process_transcript('到垃圾桶旁边去', now_ns=2)
    cancelled = core.process_transcript('取消', now_ns=3)
    core.process_transcript('小莫小莫', now_ns=10)
    core.process_transcript('到垃圾桶旁边去', now_ns=11)
    expired = core.process_transcript('确认', now_ns=10_000_000_012)

    assert cancelled.mock_output_plan is None
    assert cancelled.actual_publish_count == 0
    assert expired.mock_output_plan is None
    assert expired.actual_publish_count == 0
    assert core.has_pending is False


def test_priority_stop_is_immediate_internal_and_preempts_pending():
    core = _core()
    core.process_transcript('小莫小莫', now_ns=1)
    core.process_transcript('处理一下那个瓶子', now_ns=2)

    stopped = core.process_transcript('停下', now_ns=3)

    assert stopped.state == 'priority_stop_internal'
    assert stopped.intent == 'stop_task'
    assert core.has_pending is False
    assert stopped.stop_epoch == 1
    assert len(stopped.stop_event['repeat_attempts']) == 3
    assert stopped.stop_event['repeat_attempts'][0]['offset_ns'] == 0
    assert all(
        attempt['actual_published'] is False
        for attempt in stopped.stop_event['repeat_attempts'])
    assert all(
        attempt['payload']['schema_version'] == 3
        and attempt['payload']['process_instance_id']
        == core.process_instance_id
        for attempt in stopped.stop_event['repeat_attempts'])
    assert all(
        parse_stop_broadcast(json.dumps(attempt['payload']))[
            'process_instance_id'] == core.process_instance_id
        for attempt in stopped.stop_event['repeat_attempts'])
    assert stopped.stop_event['actual_publish_count'] == 0
    assert stopped.actual_publish_count == 0


@pytest.mark.parametrize('text', (
    '不要这么做了',
    '你休息一下吧',
    '你给我回来',
    '先不要这么干了',
    '先回来吧',
    '放下手头的活吧',
))
def test_user_recorded_natural_stop_preempts_pending_without_publish(text):
    core = _core()
    core.process_transcript('小莫小莫', now_ns=1)
    core.process_transcript('处理一下那个瓶子', now_ns=2)

    stopped = core.process_transcript(text, now_ns=3)

    assert stopped.state == 'priority_stop_internal'
    assert stopped.intent == 'stop_task'
    assert stopped.requires_confirmation is False
    assert stopped.actual_publish_count == 0
    assert stopped.production_publish_count == 0
    assert stopped.stop_event['actual_publish_count'] == 0
    assert core.has_pending is False


def test_observed_vosk_xian_huilai_alias_stays_internal_only():
    core = _core()

    stopped = core.process_transcript('行 回来 吧', now_ns=3)

    assert stopped.state == 'priority_stop_internal'
    assert stopped.intent == 'stop_task'
    assert stopped.actual_publish_count == 0
    assert stopped.production_publish_count == 0


@pytest.mark.parametrize('text', (
    '别的不说小莫捡起瓶子来是真快',
    '呃那个谁让小莫把垃圾丢一下吧',
    '没有小莫的话我们丢垃圾的活该怎么办呀',
    '你看这个小莫',
    '我觉得目前来说小莫应该做不到这样的事',
    '现在小莫的功能已经很强大了',
    '小莫的发展前景不错',
    '小莫去哪里了你有看到他吗',
    '这地上的瓶子还得小莫来捡',
    '别管那个瓶子',
    '别捡瓶子',
    '不要管地上的瓶子了',
    '不要停下',
    '不用去垃圾桶',
    '你不用捡垃圾了',
    '你不用去了',
    '你手上的工作不用再做了',
))
def test_user_recorded_related_or_negated_text_never_creates_output(text):
    core = _core()

    decision = core.process_transcript(text, now_ns=1)

    assert decision.intent == 'ignored'
    assert decision.actual_publish_count == 0
    assert decision.production_publish_count == 0
    assert core.has_pending is False
    assert core.stop_epoch == 0


def test_stop_debounce_reuses_event_without_creating_a_second_event():
    core = _core()

    first = core.process_transcript('停下', now_ns=1_000)
    duplicate = core.process_transcript('紧急停止', now_ns=750_000_999)
    boundary = core.process_transcript('停下', now_ns=750_001_000)

    assert duplicate.state == 'stop_debounced'
    assert duplicate.stop_event['event_id'] == first.stop_event['event_id']
    assert boundary.state == 'priority_stop_internal'
    assert boundary.stop_event['event_id'] != first.stop_event['event_id']
    assert boundary.stop_epoch == 2


def test_negated_or_quoted_stop_never_enters_stop_path():
    core = _core()

    negated = core.process_transcript('我没让你停下')
    quoted = core.process_transcript('“停下”这句话是什么意思')

    assert negated.intent != 'stop_task'
    assert quoted.intent != 'stop_task'
    assert core.stop_epoch == 0


def test_ack_requires_process_event_state_and_local_deadline():
    core = _core()
    stopped = core.process_transcript('停下', now_ns=100)
    event = stopped.stop_event
    ack = json.dumps(stop_ack_payload(
        event_id=event['event_id'],
        process_instance_id=core.process_instance_id,
        source='cleanup_ros1_stop_gate',
        state='accepted',
        detail='mock observed',
        wall_time_unix_ns=200,
        monotonic_ns=200,
    ), ensure_ascii=False)

    wrong_process = json.loads(ack)
    wrong_process['process_instance_id'] = 'voice-old-process-test0001'
    assert core.observe_stop_ack(
        json.dumps(wrong_process), received_monotonic_ns=200) is False
    assert core.observe_stop_ack(
        ack, received_monotonic_ns=200) is True
    assert core.observe_stop_ack(
        ack, received_monotonic_ns=1_500_000_101) is False


def test_ack_rejects_wrong_source_and_future_wall_time():
    core = _core()
    event = core.process_transcript('停下', now_ns=100).stop_event
    wrong_source = json.dumps(stop_ack_payload(
        event_id=event['event_id'],
        process_instance_id=core.process_instance_id,
        source='untrusted_stop_observer',
        state='accepted',
        detail='wrong owner',
        wall_time_unix_ns=200,
        monotonic_ns=200,
    ), ensure_ascii=False)
    future_wall = json.dumps(stop_ack_payload(
        event_id=event['event_id'],
        process_instance_id=core.process_instance_id,
        source='cleanup_ros1_stop_gate',
        state='accepted',
        detail='future wall time',
        wall_time_unix_ns=7_000_000_001,
        monotonic_ns=200,
    ), ensure_ascii=False)

    assert core.observe_stop_ack(
        wrong_source,
        received_monotonic_ns=200,
    ) is False
    assert core.observe_stop_ack(
        future_wall,
        received_monotonic_ns=200,
    ) is False


def test_ack_accepts_exact_owner_within_future_wall_tolerance():
    core = _core()
    event = core.process_transcript('停下', now_ns=100).stop_event
    valid = json.dumps(stop_ack_payload(
        event_id=event['event_id'],
        process_instance_id=core.process_instance_id,
        source='cleanup_ros1_stop_gate',
        state='accepted',
        detail='valid owner and time',
        wall_time_unix_ns=7_000_000_000,
        monotonic_ns=200,
    ), ensure_ascii=False)

    assert core.observe_stop_ack(
        valid, received_monotonic_ns=200) is True


def test_ack_json_requires_process_instance_id_inside_schema():
    core = _core()
    event = core.process_transcript('停下', now_ns=100).stop_event
    valid = stop_ack_payload(
        event_id=event['event_id'],
        process_instance_id=core.process_instance_id,
        source='cleanup_ros1_stop_gate',
        state='accepted',
        detail='valid',
        wall_time_unix_ns=200,
        monotonic_ns=200,
    )
    missing = dict(valid)
    missing.pop('process_instance_id')
    old_process = dict(valid)
    old_process['process_instance_id'] = 'voice-old-process-test0001'

    assert core.observe_stop_ack(
        json.dumps(missing), received_monotonic_ns=200) is False
    assert core.observe_stop_ack(
        json.dumps(old_process), received_monotonic_ns=200) is False
    assert core.observe_stop_ack(
        json.dumps(valid), received_monotonic_ns=200) is True


def test_rospy_wrapper_is_lazy_and_contains_no_control_interfaces():
    source = (
        PACKAGE_ROOT / 'limo_cleanup_voice'
        / 'ros1_noetic_adapter_node.py'
    ).read_text(encoding='utf-8')
    lowered = source.casefold()

    assert 'import rospy' in source
    assert source.index('def main') < source.index('import rospy')
    assert 'rospy.Publisher' not in source
    assert '/voice_mock/' not in source
    assert '/cleanup/' not in source
    assert 'cmd_vel' not in lowered
    assert 'geometry_msgs' not in lowered
    assert 'actionlib' not in lowered
    assert '/dev/' not in lowered
