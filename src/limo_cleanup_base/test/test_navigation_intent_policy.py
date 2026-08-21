from pathlib import Path

import pytest

from limo_cleanup_base.navigation_intent_policy import (
    load_map_waypoint,
    parse_navigation_intent,
)


def test_exact_cancel_contract_requires_safe_stop_true():
    intent = parse_navigation_intent(
        '{"action":"cancel_navigation","request_safe_stop":true}')
    assert intent.action == 'cancel_navigation'
    assert intent.request_safe_stop
    for payload in (
            'not-json',
            '[]',
            '{"action":"cancel_navigation"}',
            '{"action":"cancel_navigation","request_safe_stop":false}',
            '{"action":"cancel_navigation","request_safe_stop":true,'
            '"target_id":"trash_bin_staging"}'):
        with pytest.raises(ValueError):
            parse_navigation_intent(payload)


def test_only_fixed_trash_bin_waypoint_is_accepted():
    intent = parse_navigation_intent(
        '{"action":"navigate_to_waypoint",'
        '"target_id":"trash_bin_staging",'
        '"target_source":"fixed_map_waypoint"}')
    assert intent.target_id == 'trash_bin_staging'
    for payload in (
            '{"action":"navigate_to_speaker"}',
            '{"action":"navigate_to_waypoint",'
            '"target_id":"speaker","target_source":"fixed_map_waypoint"}',
            '{"action":"navigate_to_waypoint",'
            '"target_id":"trash_bin_staging","target_source":"speaker"}',
            '{"action":"navigate_to_waypoint",'
            '"target_id":"trash_bin_staging",'
            '"target_source":"fixed_map_waypoint","speaker_x":1.0}'):
        with pytest.raises(ValueError):
            parse_navigation_intent(payload)


def test_navigation_intent_rejects_duplicate_keys_and_wrong_string_types():
    malicious = (
        '{"action":"cancel_navigation","action":"navigate_to_waypoint",'
        '"request_safe_stop":true}',
        '{"action":"navigate_to_waypoint",'
        '"target_id":"trash_bin_staging",'
        '"target_id":"trash_bin_staging",'
        '"target_source":"fixed_map_waypoint"}',
        '{"action":[],"request_safe_stop":true}',
        '{"action":{},"request_safe_stop":true}',
        '{"action":true,"request_safe_stop":true}',
        '{"action":1,"request_safe_stop":true}',
        '{"action":"navigate_to_waypoint","target_id":[],'
        '"target_source":"fixed_map_waypoint"}',
        '{"action":"navigate_to_waypoint",'
        '"target_id":"trash_bin_staging","target_source":{}}',
    )
    for payload in malicious:
        with pytest.raises(ValueError):
            parse_navigation_intent(payload)


def test_navigation_intent_wraps_deep_recursion_as_value_error():
    with pytest.raises(ValueError):
        parse_navigation_intent('[' * 2000 + '0' + ']' * 2000)


def test_waypoint_requires_matching_active_v1_map(tmp_path: Path):
    path = tmp_path / 'waypoints.yaml'
    path.write_text(
        'map_id: v1_lab\n'
        'waypoints:\n'
        '  trash_bin_staging:\n'
        '    frame_id: map\n'
        '    x: 1.0\n'
        '    y: -2.0\n'
        '    yaw: 0.5\n',
        encoding='utf-8',
    )
    waypoint = load_map_waypoint(
        str(path), 'trash_bin_staging', 'v1_lab')
    assert waypoint.frame_id == 'map'
    with pytest.raises(ValueError):
        load_map_waypoint(str(path), 'trash_bin_staging', 'wrong_map')
    with pytest.raises(ValueError):
        load_map_waypoint(str(path), 'speaker', 'v1_lab')


def test_locked_unmeasured_waypoint_template_fails_closed():
    template = (
        Path(__file__).parents[1] / 'config' /
        'v1_navigation_waypoints.example.yaml')
    with pytest.raises(ValueError):
        load_map_waypoint(
            str(template),
            'trash_bin_staging',
            'NOT_AVAILABLE_MAP_NOT_FROZEN',
        )
