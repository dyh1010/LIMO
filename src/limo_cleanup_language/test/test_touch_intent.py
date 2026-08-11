from limo_cleanup_language.language_node import LanguageUnderstandingNode


def test_local_touch_bottle_intent_is_explicit():
    intent = LanguageUnderstandingNode.parse_locally(
        '请到目标地点轻触矿泉水瓶')

    assert intent['action'] == 'touch_only'
    assert intent['object_class'] == 'plastic_bottle'
    assert LanguageUnderstandingNode.intent_to_command(
        intent, 'unused') == '触碰矿泉水瓶'


def test_existing_cleanup_intent_is_unchanged():
    intent = LanguageUnderstandingNode.parse_locally('请捡矿泉水瓶')

    assert intent['action'] == 'pick_and_dispose'
    assert intent['object_class'] == 'plastic_bottle'
    assert LanguageUnderstandingNode.intent_to_command(
        intent, 'unused') == '捡塑料瓶'


def test_touch_without_supported_object_is_not_forwarded():
    intent = LanguageUnderstandingNode.parse_locally('轻触易拉罐')

    assert intent['action'] == 'unsupported'
    assert intent['object_class'] == 'can'


def test_llm_touch_intent_maps_to_same_canonical_command():
    intent = {
        'action': 'touch_only',
        'object_class': 'plastic_bottle',
    }

    assert LanguageUnderstandingNode.intent_to_command(
        intent, 'unused') == '触碰矿泉水瓶'


def test_stop_still_has_priority_over_touch_words():
    intent = LanguageUnderstandingNode.parse_locally('停止触碰矿泉水瓶')

    assert intent['action'] == 'stop'
