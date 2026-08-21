import pytest

from limo_cleanup_base.motion_policy import (
    MotionLimits,
    PermissionInputs,
    PlanarCommand,
    limited_command,
    permission_reason,
    reject_unsupported_axes,
    validate_planar_command,
    validate_limits,
)


def test_tracked_mode_accepts_only_forward_and_yaw_axes():
    reject_unsupported_axes(0.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match='linear.y'):
        reject_unsupported_axes(0.01, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match='angular.x'):
        reject_unsupported_axes(0.0, 0.0, 0.01, 0.0)
    with pytest.raises(ValueError, match='linear.y must be finite'):
        reject_unsupported_axes(float('nan'), 0.0, 0.0, 0.0)


def test_command_is_speed_and_acceleration_limited():
    limits = MotionLimits(
        max_linear_speed=0.12,
        max_angular_speed=0.35,
        max_linear_acceleration=0.20,
        max_angular_acceleration=0.60,
    )
    command = limited_command(
        PlanarCommand(linear_x=1.0, angular_z=-1.0),
        PlanarCommand(),
        dt=0.1,
        limits=limits,
    )
    assert command.linear_x == pytest.approx(0.02)
    assert command.angular_z == pytest.approx(-0.06)


def test_invalid_limits_are_rejected():
    with pytest.raises(ValueError, match='max_linear_speed'):
        validate_limits(MotionLimits(max_linear_speed=0.0))
    with pytest.raises(ValueError, match='max_angular_speed must be finite'):
        validate_limits(MotionLimits(max_angular_speed=float('nan')))


def test_non_finite_commands_and_time_steps_are_rejected():
    limits = MotionLimits()
    with pytest.raises(ValueError, match='command.linear_x must be finite'):
        limited_command(
            PlanarCommand(linear_x=float('nan')),
            PlanarCommand(),
            dt=0.1,
            limits=limits,
        )
    with pytest.raises(ValueError, match='command.angular_z must be finite'):
        validate_planar_command(PlanarCommand(angular_z=float('inf')))
    with pytest.raises(ValueError, match='dt must be finite'):
        limited_command(
            PlanarCommand(),
            PlanarCommand(),
            dt=float('inf'),
            limits=limits,
        )


def test_permission_is_fail_closed_until_every_gate_is_fresh():
    base = dict(
        allow_base_motion=True,
        now=10.0,
        request_time=9.9,
        authorization=True,
        authorization_time=9.9,
        safety_clear=True,
        safety_time=9.9,
    )
    assert permission_reason(PermissionInputs(**base)) == 'allowed'
    assert permission_reason(PermissionInputs(
        **{**base, 'allow_base_motion': False}
    )) == 'base_motion_disabled'
    assert permission_reason(PermissionInputs(
        **{**base, 'request_time': 9.0}
    )) == 'command_missing_or_stale'
    assert permission_reason(PermissionInputs(
        **{**base, 'authorization': False}
    )) == 'motion_not_authorized'
    assert permission_reason(PermissionInputs(
        **{**base, 'authorization_time': 9.0}
    )) == 'authorization_stale'
    assert permission_reason(PermissionInputs(
        **{**base, 'safety_clear': False}
    )) == 'safety_not_clear'
    assert permission_reason(PermissionInputs(
        **{**base, 'safety_time': 9.0}
    )) == 'safety_heartbeat_stale'
    assert permission_reason(PermissionInputs(
        **{
            **base,
            'require_topology_ready': True,
            'topology_ready': False,
            'topology_time': 9.9,
        }
    )) == 'topology_not_ready'
    assert permission_reason(PermissionInputs(
        **{
            **base,
            'require_topology_ready': True,
            'topology_ready': True,
            'topology_time': 9.0,
        }
    )) == 'topology_heartbeat_stale'
    assert permission_reason(PermissionInputs(
        **{
            **base,
            'require_topology_ready': True,
            'topology_ready': True,
            'topology_time': 9.9,
        }
    )) == 'allowed'


def test_permission_rejects_future_or_non_finite_timestamps():
    base = dict(
        allow_base_motion=True,
        now=10.0,
        request_time=9.9,
        authorization=True,
        authorization_time=9.9,
        safety_clear=True,
        safety_time=9.9,
    )
    assert permission_reason(PermissionInputs(
        **{**base, 'request_time': 10.1}
    )) == 'command_missing_or_stale'
    assert permission_reason(PermissionInputs(
        **{**base, 'authorization_time': float('nan')}
    )) == 'authorization_stale'
    assert permission_reason(PermissionInputs(
        **{**base, 'safety_time': float('inf')}
    )) == 'safety_heartbeat_stale'
    assert permission_reason(PermissionInputs(
        **{**base, 'command_timeout': float('nan')}
    )) == 'command_missing_or_stale'
