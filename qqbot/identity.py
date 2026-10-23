"""只过滤旧版本注入的完整身份状态段，避免误删正常讨论名字的正文。"""
import re

_LEGACY = re.compile(
    r'当前身份资料已同步（这是本轮运行时状态，不是过去的聊天发言）：'
    r'\s*\{[^{}\n]*"role_(?:name|nickname)"[^{}\n]*\}'
    r'。我将以 role_name 中的当前正式名字自我介绍，不沿用历史旧自称。'
    r'用户不问改名历史时，不提旧名字或改名过程；role_nickname 只作为昵称。')


def clean_identity_echo(text):
    return _LEGACY.sub('', text).strip()
