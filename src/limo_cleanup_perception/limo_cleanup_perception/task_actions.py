PERCEPTION_ACTIONS = ('pick_and_dispose', 'touch_only')


def accepts_perception_task(action: str) -> bool:
    return action in PERCEPTION_ACTIONS
