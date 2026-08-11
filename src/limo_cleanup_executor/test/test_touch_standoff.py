import ast
import math
from pathlib import Path

import pytest

from limo_cleanup_executor.touch_standoff import plan_touch_standoff


MODULE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_executor' / 'touch_standoff.py')


def test_touch_standoff_uses_python38_syntax():
    ast.parse(
        MODULE.read_text(encoding='utf-8'),
        filename=str(MODULE),
        feature_version=(3, 8),
    )


def test_straight_target_keeps_requested_distance():
    plan = plan_touch_standoff('map', 0.0, 0.0, 1.0, 0.0, 0.30)
    assert plan.goal_x == pytest.approx(0.70)
    assert plan.goal_y == pytest.approx(0.0)
    assert plan.goal_yaw == pytest.approx(0.0)
    assert math.hypot(
        plan.target_x - plan.goal_x,
        plan.target_y - plan.goal_y,
    ) == pytest.approx(0.30)


def test_diagonal_target_faces_target_and_preserves_ray():
    plan = plan_touch_standoff(
        'odom', 0.0, 0.0, 0.6, 0.8, 0.25)
    assert plan.target_range == pytest.approx(1.0)
    assert plan.goal_x == pytest.approx(0.45)
    assert plan.goal_y == pytest.approx(0.60)
    assert plan.goal_yaw == pytest.approx(math.atan2(0.8, 0.6))


def test_nonzero_robot_pose_is_not_treated_as_the_frame_origin():
    plan = plan_touch_standoff('map', 2.0, -1.0, 3.0, -1.0, 0.30)
    assert plan.robot_x == pytest.approx(2.0)
    assert plan.robot_y == pytest.approx(-1.0)
    assert plan.goal_x == pytest.approx(2.70)
    assert plan.goal_y == pytest.approx(-1.0)


@pytest.mark.parametrize(
    'frame_id', ('', 'base_link', 'camera_color_optical_frame'))
def test_moving_or_camera_frames_are_rejected(frame_id):
    with pytest.raises(ValueError, match='stable map/odom'):
        plan_touch_standoff(frame_id, 0.0, 0.0, 1.0, 0.0, 0.30)


@pytest.mark.parametrize('value', (float('nan'), float('inf'), -float('inf')))
def test_non_finite_geometry_is_rejected(value):
    with pytest.raises(ValueError, match='must be finite'):
        plan_touch_standoff('map', value, 0.0, 1.0, 0.0, 0.30)


def test_invalid_or_unreachable_standoff_is_rejected():
    with pytest.raises(ValueError, match='must be positive'):
        plan_touch_standoff('map', 0.0, 0.0, 1.0, 0.0, 0.0)
    with pytest.raises(ValueError, match='too close'):
        plan_touch_standoff('map', 0.0, 0.0, 0.30, 0.0, 0.30)
    with pytest.raises(ValueError, match='non-negative'):
        plan_touch_standoff(
            'map', 0.0, 0.0, 1.0, 0.0, 0.30, -0.01)
