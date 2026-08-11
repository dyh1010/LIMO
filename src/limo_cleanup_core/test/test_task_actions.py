from limo_cleanup_core.task_manager import TaskManager


def test_touch_words_select_touch_only_for_bottle():
    text = '到目标地点轻触矿泉水瓶'

    assert TaskManager.find_object_class(text) == 'plastic_bottle'
    assert TaskManager.find_action(text) == 'touch_only'


def test_existing_cleanup_command_remains_pick_and_dispose():
    text = '捡塑料瓶'

    assert TaskManager.find_object_class(text) == 'plastic_bottle'
    assert TaskManager.find_action(text) == 'pick_and_dispose'


def test_english_touch_command_is_supported():
    text = 'touch the plastic bottle'

    assert TaskManager.find_object_class(text) == 'plastic_bottle'
    assert TaskManager.find_action(text) == 'touch_only'


def test_cancel_keyword_does_not_look_like_touch():
    assert TaskManager.find_action('停止任务') == 'pick_and_dispose'


def test_touch_only_has_no_implicit_object_fallback():
    text = '轻触目标'

    assert TaskManager.find_action(text) == 'touch_only'
    assert TaskManager.find_object_class(text) is None
