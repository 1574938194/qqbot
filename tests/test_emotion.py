from qqbot.emotion import advance, decay, describe, hint


def test_emotion_decay_bonding_and_negation():
    state = advance(None, '我今天很难过', now=10000)
    assert state.mood == '低落' and state.valence < 0
    assert state.familiarity == 20.5
    next_state = advance(state.dump(), '我有点紧张', now=10001)
    assert next_state.mood == '焦虑'
    assert next_state.familiarity == state.familiarity
    old = decay(next_state, now=10001 + 86400)
    assert old.mood == '平静' and old.confidence < .2
    assert old.familiarity == next_state.familiarity
    assert advance(None, '我不难过', now=10000).mood == '平静'
    assert advance(None, '我的朋友今天因为考试失败很难过', now=10000).mood == '平静'
    assert '规则估算' in describe(old) and '不因离线责怪' in hint(old)
