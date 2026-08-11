import pytest

from limo_cleanup_perception.task_actions import accepts_perception_task


@pytest.mark.parametrize('action', ('pick_and_dispose', 'touch_only'))
def test_perception_accepts_supported_task_actions(action):
    assert accepts_perception_task(action)


@pytest.mark.parametrize(
    'action', ('', 'cancel', 'throw_bottle', 'mycobot_follow'))
def test_perception_rejects_all_other_task_actions(action):
    assert not accepts_perception_task(action)
