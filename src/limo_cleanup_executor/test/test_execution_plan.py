import pytest

from limo_cleanup_executor.execution_plan import (
    ACTION_PICK_AND_DISPOSE,
    ACTION_TOUCH_ONLY,
    PICK_AND_DISPOSE_STEPS,
    TOUCH_ONLY_STEPS,
    execution_steps,
    normalize_action,
    validate_mock_safety,
    validate_goal,
)


def test_existing_action_keeps_original_pick_and_dispose_steps():
    assert execution_steps(ACTION_PICK_AND_DISPOSE) == PICK_AND_DISPOSE_STEPS
    assert [step[0] for step in PICK_AND_DISPOSE_STEPS] == [
        'approaching_object',
        'aligning_object',
        'grasping',
        'verifying_grasp',
        'navigating_to_bin',
        'aligning_bin',
        'dropping',
        'verifying_drop',
    ]


def test_empty_action_is_backward_compatible():
    assert normalize_action('') == ACTION_PICK_AND_DISPOSE


def test_touch_only_uses_exact_safe_sequence():
    assert execution_steps(ACTION_TOUCH_ONLY) == TOUCH_ONLY_STEPS
    assert [step[0] for step in TOUCH_ONLY_STEPS] == [
        'planning_standoff',
        'navigating_to_standoff',
        'aligning_touch_pose',
        'pre_touch',
        'touching',
        'retreating',
    ]


def test_touch_only_has_no_grasp_drop_bin_or_gripper_stage():
    serialized = ' '.join(
        '{} {}'.format(state, detail)
        for state, _, detail in TOUCH_ONLY_STEPS
    ).lower()
    for forbidden in ('grasp', 'drop', 'bin', 'gripper'):
        assert forbidden not in serialized


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError, match='unsupported cleanup action'):
        execution_steps('throw_bottle')


def test_touch_goal_requires_bottle_and_identifiers():
    assert validate_goal(
        ACTION_TOUCH_ONLY, 'plastic_bottle', 'task-1') == ACTION_TOUCH_ONLY
    with pytest.raises(ValueError, match='plastic_bottle only'):
        validate_goal(ACTION_TOUCH_ONLY, 'can', 'task-1')
    with pytest.raises(ValueError, match='task_id is required'):
        validate_goal(ACTION_TOUCH_ONLY, 'plastic_bottle', '')
    with pytest.raises(ValueError, match='object_class is required'):
        validate_goal(ACTION_TOUCH_ONLY, '', 'task-1')


def test_legacy_cleanup_goal_remains_supported():
    assert validate_goal(
        ACTION_PICK_AND_DISPOSE, 'plastic_bottle', 'task-2'
    ) == ACTION_PICK_AND_DISPOSE


def test_mock_safety_is_fail_closed():
    validate_mock_safety(dry_run=True, allow_arm_motion=False)
    with pytest.raises(ValueError, match='dry_run=true'):
        validate_mock_safety(dry_run=False, allow_arm_motion=False)
    with pytest.raises(ValueError, match='allow_arm_motion=false'):
        validate_mock_safety(dry_run=True, allow_arm_motion=True)
