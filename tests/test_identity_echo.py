from types import SimpleNamespace
from unittest.mock import AsyncMock

from qqbot.config import ADMIN, Settings
from qqbot.identity import clean_identity_echo
from qqbot.service import Service
from qqbot.store import Store

LEGACY = ('当前身份资料已同步（这是本轮运行时状态，不是过去的聊天发言）：'
          '{"role_name": "梦梦", "role_nickname": "姚菱心"}'
          '。我将以 role_name 中的当前正式名字自我介绍，不沿用历史旧自称。'
          '用户不问改名历史时，不提旧名字或改名过程；role_nickname 只作为昵称。')


async def test_echo_removed_from_model_history_reply_and_summary_without_changing_db(tmp_path):
    store = Store(str(tmp_path / 'db'))
    try:
        store.set_prompt('原始人设不变')
        store.set_identity(name='梦梦')
        store.append(ADMIN, '你好', '旧回复\n' + LEGACY)
        llm = SimpleNamespace(complete=AsyncMock(return_value='新回复\n' + LEGACY))
        service = Service(store, llm, Settings())
        messages = service.messages(ADMIN, '今天怎么样')
        assert LEGACY not in str(messages)
        assert messages[-2] == {'role': 'assistant', 'content': '旧回复'}
        assert await service.handle(ADMIN, '今天怎么样') == '新回复'
        assert store.history(ADMIN)[0][2] == '旧回复\n' + LEGACY
        assert store.history(ADMIN)[1][2] == '新回复'
        assert store.prompt() == '原始人设不变'
        for i in range(6):
            store.append(ADMIN, str(i), '回复')
        await service.compress(ADMIN)
        assert LEGACY not in str(llm.complete.call_args.args[0])
    finally:
        store.close()


async def test_internal_echo_only_is_not_a_successful_turn(tmp_path):
    store = Store(str(tmp_path / 'db'))
    try:
        llm = SimpleNamespace(complete=AsyncMock(return_value=LEGACY))
        assert '没有返回正文' in await Service(store, llm, Settings()).handle(ADMIN, '你好')
        assert not store.history(ADMIN)
    finally:
        store.close()


def test_normal_field_discussion_is_preserved():
    text = 'role_name 是数据库字段，你可以通过 /profile name 修改。'
    assert clean_identity_echo(text) == text
