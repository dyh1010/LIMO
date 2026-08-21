"""Static safety checks for the pure orchestration consumer helper."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_perception/orchestration_contract.py'
).read_text(encoding='utf-8')


def test_orchestration_helper_has_no_ros_or_motion_api():
    """Target selection must remain a pure read-only function."""
    assert 'rclpy' not in SOURCE
    assert 'create_publisher(' not in SOURCE
    assert '.publish(' not in SOURCE
    assert 'Twist' not in SOURCE
    assert 'NavigateToPose' not in SOURCE
    assert '/cmd_vel' not in SOURCE
    assert 'ActionClient' not in SOURCE
    assert 'ActionServer' not in SOURCE
    assert 'create_client(' not in SOURCE
    assert 'create_service(' not in SOURCE
    assert 'serial' not in SOURCE
    assert 'socket' not in SOURCE


def test_orchestration_helper_rejects_stale_and_duplicate_input():
    """Freshness and replay rejection are part of the consumer contract."""
    assert "_rejected('frame_stale'" in SOURCE
    assert "_rejected('duplicate_or_stale_sequence'" in SOURCE
    assert "_rejected('duplicate_observation'" in SOURCE
    assert "_rejected('frame_status_invalid'" in SOURCE
    assert "target.get('status') != 'active'" in SOURCE
    assert "target.get('status') != 'observed'" in SOURCE


if __name__ == '__main__':
    test_orchestration_helper_has_no_ros_or_motion_api()
    test_orchestration_helper_rejects_stale_and_duplicate_input()
    print('2 orchestration source-contract checks passed')
