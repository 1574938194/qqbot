"""有界、可解释的回复风格状态；仅为规则估算，不是心理诊断。"""
import math
import re
import time
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Emotion:
    mood: str = "平静"
    confidence: float = 0.0
    valence: float = 0.0
    arousal: float = 0.3
    familiarity: float = 20.0
    turns: int = 0
    updated_at: float = 0.0
    last_bond_at: float = 0.0

    def dump(self):
        return asdict(self)


MOODS = {
    "低落": (r"难过|伤心|失落|委屈|想哭", -.7, .35),
    "焦虑": (r"焦虑|紧张|担心|害怕|压力大", -.5, .8),
    "疲惫": (r"好累|很累|累了|疲惫|困了|睡不着", -.25, .15),
    "生气": (r"生气|愤怒|气死|烦躁", -.6, .85),
    "开心": (r"开心|高兴|幸福|兴奋|太棒了", .8, .65),
    "孤单": (r"孤独|孤单|想你|寂寞", -.4, .3),
}


def decay(previous=None, *, now=None):
    now = time.time() if now is None else now
    state = Emotion(**previous) if isinstance(previous, dict) else previous or Emotion()
    hours = max(0, now - state.updated_at) / 3600 if state.updated_at else 0
    factor = math.pow(.5, hours / 6)
    confidence = state.confidence * factor
    return replace(state, mood=state.mood if confidence >= .2 else "平静", confidence=confidence,
                   valence=state.valence * factor, arousal=.3 + (state.arousal - .3) * factor,
                   updated_at=now)


def advance(previous, text, *, now=None):
    now = time.time() if now is None else now
    state = decay(previous, now=now)
    # 仅采用第一人称自述/常见简短情绪表达，避免把第三人的情绪当成用户状态。
    evidence = ' '.join(clause for clause in re.split(r'[，。！？!?；;\n]', text)
                        if ('我' in clause or len(clause.strip()) <= 6)
                        and not re.search(r'(?:我的?|他|她)的?(?:朋友|同事|家人|同学|妈妈|爸爸|对象)', clause)
                        and not re.search(r'(?:他说|她说|朋友说|例如|比如|假如|如果|[“"「])', clause))
    # 消除常见直接否定；复杂反讽、引用仍可能误判，输出明确标注估算。
    evidence = re.sub(r'(?:不再|没有|没那么|不|没)(?:太|很|再)?(?:' + '|'.join(v[0] for v in MOODS.values()) + r')', '', evidence)
    observed = next(((mood, valence, arousal) for mood, (pattern, valence, arousal) in MOODS.items()
                     if re.search(pattern, evidence)), None)
    if observed:
        mood, valence, arousal = observed
        state = replace(state, mood=mood, confidence=.7, valence=valence, arousal=arousal)
    # 每半小时至多增长一次；不因离线、拒绝亲密或负面情绪扣分。
    bond = not state.last_bond_at or now - state.last_bond_at >= 1800
    return replace(state, familiarity=min(100, state.familiarity + (.5 if bond else 0)),
                   last_bond_at=now if bond else state.last_bond_at, turns=state.turns + 1)


def hint(state):
    style = {
        "低落": "先温柔接住感受，少给建议", "焦虑": "沉稳、简短，陪用户把眼前事情理清",
        "疲惫": "放轻语气，减少追问", "生气": "理解情绪，避免火上浇油",
        "开心": "自然分享喜悦", "孤单": "温暖陪伴，尊重现实中的关系", "平静": "自然闲聊",
    }[state.mood]
    return (f"回复风格参考：用户情绪暂估为{state.mood}，置信度{state.confidence:.0%}；"
            f"互动熟悉度{state.familiarity:.0f}/100。{style}。这些是可错的规则估算，"
            "以用户当下表述为准，不给用户贴标签，不主动报分数。熟悉度仅调节自然程度，"
            "不升级关系承诺，不因离线责怪、吃醋或索取陪伴。")


def describe(state):
    return (f"情绪：{state.mood}（规则估算，置信度 {state.confidence:.0%}）\n"
            f"情绪倾向：{state.valence:+.2f}；活跃度：{state.arousal:.2f}\n"
            f"互动熟悉度：{state.familiarity:.1f}/100；成功互动：{state.turns} 轮")
