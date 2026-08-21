"""Pure parsing and waypoint validation for V2 navigation intents."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from limo_cleanup_base.strict_json import loads_strict


TRASH_BIN_WAYPOINT = 'trash_bin_staging'


@dataclass(frozen=True)
class NavigationIntent:
    """Validated high-level navigation intent."""

    action: str
    target_id: str = ''
    request_safe_stop: bool = False


@dataclass(frozen=True)
class MapWaypoint:
    """One fixed waypoint tied to a named V1 map."""

    map_id: str
    target_id: str
    frame_id: str
    x: float
    y: float
    yaw: float


def parse_navigation_intent(payload: str) -> NavigationIntent:
    """Accept only the verified voice V2 JSON contract."""
    data = loads_strict(payload, 'navigation intent')
    if not isinstance(data, dict):
        raise ValueError('navigation intent JSON must be an object')
    action = data.get('action')
    if not isinstance(action, str) or action != action.strip():
        raise ValueError('navigation intent action must be a trimmed string')
    if action == 'cancel_navigation':
        unknown_keys = set(data) - {'action', 'request_safe_stop'}
        if unknown_keys:
            raise ValueError(
                'cancel_navigation contains unsupported fields: {}'.format(
                    ', '.join(sorted(unknown_keys))))
        if data.get('request_safe_stop') is not True:
            raise ValueError(
                'cancel_navigation requires request_safe_stop=true')
        return NavigationIntent(
            action=action,
            request_safe_stop=True,
        )
    if action == 'navigate_to_waypoint':
        unknown_keys = set(data) - {
            'action', 'target_id', 'target_source'}
        if unknown_keys:
            raise ValueError(
                'navigate_to_waypoint contains unsupported fields: {}'.format(
                    ', '.join(sorted(unknown_keys))))
        target_id = data.get('target_id')
        target_source = data.get('target_source')
        if not isinstance(target_id, str) or target_id != target_id.strip():
            raise ValueError('waypoint target_id must be a trimmed string')
        if (
                not isinstance(target_source, str)
                or target_source != target_source.strip()):
            raise ValueError('waypoint target_source must be a trimmed string')
        if target_id != TRASH_BIN_WAYPOINT:
            raise ValueError('only trash_bin_staging is supported')
        if target_source != 'fixed_map_waypoint':
            raise ValueError('waypoint target_source must be fixed_map_waypoint')
        return NavigationIntent(action=action, target_id=target_id)
    raise ValueError('unsupported navigation action: {}'.format(action))


def _finite_number(mapping: Mapping, key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('waypoint {} must be a number'.format(key))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('waypoint {} must be finite'.format(key))
    return value


def load_map_waypoint(
        waypoint_file: str,
        target_id: str,
        expected_map_id: str) -> MapWaypoint:
    """Load one fixed waypoint only when it belongs to the active V1 map."""
    path = Path(waypoint_file)
    if not waypoint_file or not path.is_file():
        raise ValueError('V1 waypoint file is missing')
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except Exception as error:
        raise ValueError('V1 waypoint file could not be parsed') from error
    if not isinstance(data, dict):
        raise ValueError('V1 waypoint file must contain a mapping')
    map_id = str(data.get('map_id', '')).strip()
    if not expected_map_id or map_id != expected_map_id:
        raise ValueError(
            'waypoint map_id {} does not match active V1 map {}'.format(
                map_id or '<empty>', expected_map_id or '<empty>'))
    waypoints = data.get('waypoints')
    if not isinstance(waypoints, dict) or target_id not in waypoints:
        raise ValueError(
            'waypoint {} does not exist in active V1 map'.format(target_id))
    waypoint = waypoints[target_id]
    if not isinstance(waypoint, dict):
        raise ValueError('waypoint entry must be a mapping')
    frame_id = str(waypoint.get('frame_id', '')).strip()
    if frame_id != 'map':
        raise ValueError('waypoint frame_id must be map')
    return MapWaypoint(
        map_id=map_id,
        target_id=target_id,
        frame_id=frame_id,
        x=_finite_number(waypoint, 'x'),
        y=_finite_number(waypoint, 'y'),
        yaw=_finite_number(waypoint, 'yaw'),
    )
