import math
from dataclasses import dataclass


STABLE_NAVIGATION_FRAMES = ('map', 'odom')


@dataclass(frozen=True)
class TouchStandoffPlan:
    frame_id: str
    robot_x: float
    robot_y: float
    target_x: float
    target_y: float
    goal_x: float
    goal_y: float
    goal_yaw: float
    target_range: float
    standoff_distance: float


def _finite(name: str, value: float) -> float:
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError('{} must be finite'.format(name))
    return resolved


def plan_touch_standoff(
        frame_id: str,
        robot_x: float,
        robot_y: float,
        target_x: float,
        target_y: float,
        standoff_distance: float,
        minimum_goal_range: float = 0.05) -> TouchStandoffPlan:
    """Plan a planar goal before a target without sending any command."""
    resolved_frame = (frame_id or '').strip()
    if resolved_frame not in STABLE_NAVIGATION_FRAMES:
        raise ValueError(
            'touch standoff requires a stable map/odom target frame; got '
            '{}'.format(resolved_frame or 'empty'))

    base_x = _finite('robot_x', robot_x)
    base_y = _finite('robot_y', robot_y)
    x = _finite('target_x', target_x)
    y = _finite('target_y', target_y)
    distance = _finite('standoff_distance', standoff_distance)
    minimum_range = _finite('minimum_goal_range', minimum_goal_range)
    if distance <= 0.0:
        raise ValueError('standoff_distance must be positive')
    if minimum_range < 0.0:
        raise ValueError('minimum_goal_range must be non-negative')

    delta_x = x - base_x
    delta_y = y - base_y
    target_range = math.hypot(delta_x, delta_y)
    if target_range <= distance + minimum_range:
        raise ValueError(
            'target is too close for the requested standoff distance')

    goal_range = target_range - distance
    unit_x = delta_x / target_range
    unit_y = delta_y / target_range
    goal_x = base_x + unit_x * goal_range
    goal_y = base_y + unit_y * goal_range

    return TouchStandoffPlan(
        frame_id=resolved_frame,
        robot_x=base_x,
        robot_y=base_y,
        target_x=x,
        target_y=y,
        goal_x=goal_x,
        goal_y=goal_y,
        goal_yaw=math.atan2(delta_y, delta_x),
        target_range=target_range,
        standoff_distance=distance,
    )
