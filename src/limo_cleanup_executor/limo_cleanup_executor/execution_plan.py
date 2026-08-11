ACTION_PICK_AND_DISPOSE = 'pick_and_dispose'
ACTION_TOUCH_ONLY = 'touch_only'

PICK_AND_DISPOSE_STEPS = (
    ('approaching_object', 0.25, 'Approaching the detected object'),
    ('aligning_object', 0.35, 'Aligning the chassis for pickup'),
    ('grasping', 0.50, 'Closing the gripper around the object'),
    ('verifying_grasp', 0.60, 'Verifying that the object was grasped'),
    ('navigating_to_bin', 0.75, 'Navigating to the trash bin'),
    ('aligning_bin', 0.85, 'Aligning with the trash bin'),
    ('dropping', 0.93, 'Dropping the object into the bin'),
    ('verifying_drop', 0.98, 'Verifying that the object was released'),
)

TOUCH_ONLY_STEPS = (
    (
        'planning_standoff', 0.25,
        'Planning a safe standoff without commanding hardware',
    ),
    (
        'navigating_to_standoff', 0.35,
        'Simulating navigation to the safe standoff in dry-run',
    ),
    (
        'aligning_touch_pose', 0.45,
        'Simulating end-effector touch-pose alignment in dry-run',
    ),
    (
        'pre_touch', 0.60,
        'Moving to the bounded pre-touch pose in dry-run',
    ),
    (
        'touching', 0.75,
        'Executing one bounded light-touch segment in dry-run',
    ),
    (
        'retreating', 0.90,
        'Retreating to the pre-touch pose in dry-run',
    ),
)


def normalize_action(action: str) -> str:
    resolved = (action or '').strip()
    if not resolved:
        return ACTION_PICK_AND_DISPOSE
    if resolved not in (ACTION_PICK_AND_DISPOSE, ACTION_TOUCH_ONLY):
        raise ValueError('unsupported cleanup action: {}'.format(resolved))
    return resolved


def execution_steps(action: str):
    resolved = normalize_action(action)
    if resolved == ACTION_TOUCH_ONLY:
        return TOUCH_ONLY_STEPS
    return PICK_AND_DISPOSE_STEPS


def validate_goal(action: str, object_class: str, task_id: str) -> str:
    resolved = normalize_action(action)
    if not (task_id or '').strip():
        raise ValueError('task_id is required')
    if not (object_class or '').strip():
        raise ValueError('object_class is required')
    if (
            resolved == ACTION_TOUCH_ONLY
            and object_class != 'plastic_bottle'):
        raise ValueError('touch_only supports plastic_bottle only')
    return resolved


def validate_mock_safety(dry_run: bool, allow_arm_motion: bool) -> None:
    if not dry_run:
        raise ValueError(
            'mock executor requires dry_run=true; no arm backend is installed')
    if allow_arm_motion:
        raise ValueError(
            'mock executor requires allow_arm_motion=false')
